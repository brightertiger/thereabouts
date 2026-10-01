"""Compare re-reconciled countries at the same r8 centres as a saved golden baseline."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import h3

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, write_json
from build_data.reconcile.common import Row
from build_data.reconcile.lookup import Locator

from .inputs import Inputs, discover
from .quality import named, probes, settlements


class CentreReader:
    """Use the independent scalar oracle, without building or changing cells."""

    def __init__(self, locator: Locator) -> None:
        self.locator = locator

    def lookup(self, cell: str | None) -> Row:
        if cell is None:
            return {"cell_status": "unlocated"}
        if h3.get_resolution(cell) != 8:
            raise ValueError("Expected a resolution-8 centre")
        answer = self.locator.locate(*h3.cell_to_latlng(cell))
        return {
            **{
                role + "_id": (answer[role] or {}).get("id")
                for role in ("country", "state", "city")
            },
            "city_method": answer["city_method"],
            "land_method": answer["land_method"],
            "cell_status": "matched"
            if answer["country"]
            else "unassigned"
            if answer["eligible"]
            else "ineligible",
        }


def compare(
    workspace: Workspace, baseline: Path, countries: list[str], output: Path
) -> Row:
    old = read_json(baseline / "reconciled-v0.json")
    quality = read_json(baseline / "quality-v0.json")["checks"]
    current = discover(workspace)
    if not set(countries) <= current.countries.keys():
        raise ValueError("Sample includes an unfinished country")
    # Unchanged neighbours retain their v0 borders until their turn. Every
    # selected country's new checkpoint is verified by discover().
    inputs = Inputs(
        {**old["countries"], **current.countries},
        current.land,
        current.policy,
        current.sources,
        current.builder,
    )
    before: Counter[str] = Counter()
    after: Counter[str] = Counter()
    reports = {}
    with Locator(inputs.paths, Path(inputs.land["path"]), inputs.policy) as locator:
        reader = CentreReader(locator)
        for cc in countries:
            report = settlements(reader, inputs, cc)
            previous = quality["settlements"][cc]["counts"]
            before.update(previous)
            after.update(report["counts"])
            reports[cc] = {
                "before": previous,
                "after": report["counts"],
                "failures": report["failures"],
            }
            print(
                f"sample {cc}: {previous.get('city_same_identity', 0)} -> "
                f"{report['counts'].get('city_same_identity', 0)} / "
                f"{report['counts'].get('total', 0)}",
                flush=True,
            )
        fixtures = named(reader, inputs)
        extra = probes(reader, inputs)
    improved = (
        after["city_same_identity"] > before["city_same_identity"]
        and after["country_agrees"] >= before["country_agrees"]
        and after["state_agrees"] >= before["state_agrees"]
        and all(r["passed"] for r in fixtures)
    )
    value = {
        "improved": improved,
        "countries": countries,
        "before": dict(before),
        "after": dict(after),
        "reports": reports,
        "named": fixtures,
        "probes": extra,
        "builder": current.builder,
        "policy_hash": fingerprint(current.policy),
        "inputs": fingerprint(current.sources),
        "definition": "Before: stored v0 cells. After: independent scalar oracle at "
        "exactly the same r8 centres, using re-reconciled sample countries and v0 "
        "neighbours. Final world checks run through stored v1 cells.",
    }
    write_json(output, value)
    print(
        f"sample improvement gate: {improved}; exact "
        f"{before['city_same_identity']} -> {after['city_same_identity']}",
        flush=True,
    )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--countries", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = compare(
        Workspace(args.data_dir.resolve()),
        args.baseline,
        sorted(set(args.countries)),
        args.output,
    )
    if not value["improved"]:
        raise SystemExit("Sample did not pass; do not start the world rebuild")


if __name__ == "__main__":
    main()

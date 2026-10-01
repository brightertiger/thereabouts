"""CLI: verified source extraction, country units, quality gate and status."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import file_record, read_json
from build_data.acquire.io import fingerprint, write_json
from build_data.acquire.runtime import resources, single_run

from .build import build_country, country_output
from .common import builder_hash, policy
from .inputs import extract, query_engine, sovereigns, verified_inputs
from .land import build_land
from .manifest import publish, status
from .retirement import begin, retire_country


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "status"), nargs="?", default="run")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--countries", nargs="+")
    parser.add_argument("--world", action="store_true")
    parser.add_argument("--improvement-gate", type=Path)
    parser.add_argument("--stage", choices=("all", "build", "quality"), default="all")
    args = parser.parse_args()
    workspace = Workspace(args.data_dir.resolve())
    if args.command == "status":
        print(json.dumps(status(workspace), indent=2))
        return
    selected_policy = policy()
    countries = sorted(set(args.countries or selected_policy["pilot"]))
    if any(
        len(c) != 2 or not c.isascii() or not c.isalpha() or c != c.upper()
        for c in countries
    ):
        parser.error("--countries requires uppercase two-letter codes, including XK")
    started = time.monotonic()
    with single_run(workspace, "reconcile"):
        workspace.check_budget()
        paths, sources = verified_inputs(workspace)
        inputs, builder = fingerprint(sources), builder_hash()
        work = workspace.work / "reconcile"
        work.mkdir(parents=True, exist_ok=True)
        db = query_engine(paths, work)
        try:
            sovereigns(db, selected_policy)
            write_json(
                work / "run.json",
                {
                    "world": args.world,
                    "stage": args.stage,
                    "completed": False,
                    "builder": builder,
                },
            )
            if args.world:
                if args.improvement_gate:
                    sample = read_json(args.improvement_gate)
                    if (
                        not sample.get("improved")
                        or sample.get("builder") != builder
                        or sample.get("policy_hash") != fingerprint(selected_policy)
                        or sample.get("inputs") != inputs
                    ):
                        raise ValueError(
                            "World run requires a current passing improvement gate"
                        )
                gate = read_json(workspace.root / "reconciled" / "pilot.json")
                if (
                    not gate["passed"]
                    or not Ledger(workspace.ledger_path).is_complete(
                        "reconcile.gate", "pilot", fingerprint(gate)
                    )
                    or gate["policy_hash"] != fingerprint(selected_policy)
                    or gate["builder"] != builder
                    or gate["inputs"] != inputs
                ):
                    raise ValueError(
                        "World run requires a passing pilot for these exact "
                        "inputs/code/policy"
                    )
                countries = [
                    r[0]
                    for r in db.execute(
                        "SELECT country_code FROM overture_areas "
                        "WHERE country_code IS NOT NULL UNION "
                        "SELECT country_code FROM geonames_places "
                        "WHERE country_code IS NOT NULL UNION "
                        "SELECT country_code FROM geoboundaries_areas "
                        "WHERE country_code IS NOT NULL ORDER BY 1"
                    ).fetchall()
                ]
            land = build_land(
                workspace, paths["osm_land_areas"], fingerprint(sources["osm_land"])
            )
            begin(workspace, selected_policy, sources, file_record(land), builder)
            outputs: dict[str, Path] = {}
            for cc in countries:
                if builder_hash() != builder:
                    raise RuntimeError("Reconciliation code changed during run; resume")
                workspace.check_budget()
                digest, output = country_output(
                    workspace, cc, inputs, selected_policy, builder
                )
                if not Ledger(workspace.ledger_path).is_complete(
                    "reconcile.country", cc, digest
                ):
                    root = extract(workspace, db, cc, inputs)
                    output = build_country(
                        workspace, root, cc, inputs, selected_policy, builder
                    )
                outputs[cc] = output
                retire_country(workspace, cc, output, digest)
            reports: dict[str, Path] = {}
            if args.stage != "build":
                from .quality import evaluate

                reports = evaluate(
                    workspace, outputs, land, selected_policy, inputs, builder
                )
            publish(
                workspace, outputs, land, selected_policy, sources, reports, builder
            )
            write_json(
                work / "run.json",
                {
                    "countries": countries,
                    "stage": args.stage,
                    "world": args.world,
                    "resources": resources(started),
                    "completed": True,
                },
            )
            print(json.dumps(resources(started)), flush=True)
        finally:
            db.close()


if __name__ == "__main__":
    main()

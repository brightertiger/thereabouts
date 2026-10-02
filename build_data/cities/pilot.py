"""Measure the nine-country pilot with town radii off and on before any world run."""

import argparse
from collections import Counter
from pathlib import Path

from build_data.acquire import Workspace
from build_data.acquire.artifacts import file_record, read_json
from build_data.acquire.io import fingerprint, sha256_file, write_json
from build_data.golden.inputs import discover
from build_data.golden.reader import Cells
from build_data.reconcile.common import Row

from .engine import Engine
from .evaluate import Comparison
from .quality import country_report, named_checks
from .urban import Urban


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("data/work/v2-pilot"))
    args = parser.parse_args()
    workspace = Workspace(args.data_dir.resolve())
    inputs = discover(workspace)
    normalized = read_json(workspace.root / "city_normalized/manifest.json")
    base = read_json(workspace.root / "golden/manifest.json")
    if not base["completed"]:
        raise ValueError("Pilot requires a verified complete base golden")
    reader = Cells(base["tables"])
    urban = Urban(normalized["ghsl"]["partitions"])
    probes = read_json(Path(__file__).with_name("probes.json"))
    totals: dict[str, Counter[str]] = {"off": Counter(), "on": Counter()}
    summary: Row = {
        "normalization": fingerprint(normalized),
        "base": fingerprint(base),
        "variants": {},
    }
    named_results = {}
    for variant, radius in [("off", False), ("on", True)]:
        reports = {}
        for cc in normalized["policy"]["pilot"]:
            engine = Engine(
                Path(normalized["countries"][cc]["index"]["path"]),
                inputs.paths[cc],
                urban,
                normalized["policy"],
                (Path(inputs.land["path"]), inputs.policy["offshore_m"]),
            )
            comparison = Comparison(reader, {cc: engine}, radius)
            path = args.output / variant / f"{cc}.json"
            digest = fingerprint(
                {
                    "normalization": normalized["countries"][cc]["digest"],
                    "base": summary["base"],
                    "radius": radius,
                    "evaluation": {
                        p.name: sha256_file(p)
                        for p in Path(__file__).parent.iterdir()
                        if p.suffix in {".py", ".json"}
                    },
                }
            )
            if path.exists() and read_json(path).get("inputs_hash") == digest:
                report = read_json(path)
            else:
                report = country_report(comparison, cc, engine, urban, probes)
                report["named"] = [
                    r for r in named_checks(comparison, inputs) if r["country"] == cc
                ]
                report["inputs_hash"] = digest
                write_json(path, report)
            named_results[cc] = report["named"]
            totals[variant].update(report["diagnostic"]["counts"])
            path = args.output / variant / f"{cc}.json"
            write_json(path, report)
            reports[cc] = str(path.resolve())
            print(variant, cc, report["diagnostic"]["counts"], flush=True)
        # Unchanged nonpilot named fixtures are still evaluated through real base cells.
        named = [
            r
            for r in named_checks(Comparison(reader, {}, radius), inputs)
            if r["country"] not in named_results
        ]
        named.extend(r for rows in named_results.values() for r in rows)
        all_reports = [read_json(Path(p)) for p in reports.values()]
        bad_footprints = [
            f
            for r in all_reports
            for f in r["footprints"]
            if f["after"]["eligible"] and f["after"]["share"] < 0.99
        ]
        bad_neighbours = [
            n
            for r in all_reports
            for n in r["neighbours"]
            if n.get("error")
            or n["point_after"].get("city_id") != n["city_id"]
            or n["polygon_after"]["expected"] < n["polygon_before"]["expected"]
        ]
        losses = [
            c for r in all_reports for c in r["diagnostic"]["changes"] if c["loss"]
        ]
        summary["variants"][variant] = {
            "counts": dict(totals[variant]),
            "countries": reports,
            "report_artifacts": [file_record(Path(p)) for p in reports.values()],
            "named": named,
            "bad_footprints": bad_footprints,
            "bad_neighbours": bad_neighbours,
            "diagnostic_losses": losses,
            "automated_gate": not bad_footprints
            and not bad_neighbours
            and all(r["passed"] for r in named),
        }
        write_json(args.output / "summary.json", summary)
    print(
        "Pilot complete; review losses and patch changes "
        "before recording a world gate.",
        flush=True,
    )


if __name__ == "__main__":
    main()

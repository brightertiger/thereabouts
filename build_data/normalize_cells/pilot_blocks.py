"""Materialize pilot probe blocks and a real country catalogue beside frozen v1."""

import argparse
import json
from collections import Counter
from pathlib import Path

import h3
import pyarrow.parquet as pq

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, write_json
from build_data.cities.common import builder
from build_data.cities.engine import Engine
from build_data.cities.evaluate import Comparison
from build_data.cities.quality import named_checks
from build_data.cities.urban import Urban
from build_data.golden.inputs import discover, verify_record
from build_data.golden.reader import Cells
from build_data.normalize_cells.base import load
from build_data.reconcile.common import Row

from .blocks import build
from .run import implementation
from .tables import places
from .verify import reference_checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    workspace = Workspace(args.data_dir.resolve())
    inputs = discover(workspace)
    normalized = read_json(workspace.root / "city_normalized/manifest.json")
    if normalized["builder"] != builder():
        raise ValueError("Stale country normalization; regenerate pilot first")
    base = load(workspace, inputs)[1]
    urban = Urban(normalized["ghsl"]["partitions"])
    engines = {
        cc: Engine(
            Path(report["index"]["path"]),
            inputs.paths[cc],
            urban,
            normalized["policy"],
            (Path(inputs.land["path"]), inputs.policy["offshore_m"]),
        )
        for cc, report in normalized["countries"].items()
    }
    probes = read_json(Path(__file__).parents[1] / "cities/probes.json")
    fixtures = json.loads(
        (Path(__file__).parents[1] / "reconcile/fixtures.json").read_text()
    )
    points = [(r[1], r[2]) for r in [*probes["named"], *fixtures] if r[3] in engines]
    points.extend(
        (r["latitude"], r["longitude"])
        for cc, engine in engines.items()
        for r in engine.cities
        if r["city_id"] in probes["neighbours"].get(cc, {})
    )
    roots = {h3.cell_to_parent(h3.latlng_to_cell(y, x, 8), 3) for y, x in points}
    records = [
        r for r in base["tables"] if r["kind"] == "cells" and r["block"] in roots
    ]
    identity = fingerprint(
        {"normalization": normalized, "implementation": implementation()}
    )
    output = workspace.work / "v2-pilot-blocks"
    reports: Row = {}
    for variant, radius in [("off", False), ("on", True)]:
        tables = []
        counts: dict[str, Row] = {}
        for record in records:
            verify_record(record)
            countries = {
                c.removeprefix("country:")
                for c in pq.read_table(record["path"], columns=["country_id"])[
                    "country_id"
                ]
                .unique()
                .to_pylist()
                if c
            }
            if not countries <= engines.keys():
                raise ValueError("Pilot probe block includes a nonpilot country")
            result = build(
                workspace,
                output / variant,
                record,
                {cc: engines[cc] for cc in countries},
                identity,
                radius,
            )
            tables.append(result["table"])
            for cc, values in result["countries"].items():
                count = counts.setdefault(
                    cc,
                    {"eligible": 0, "changed_city": 0, "method_transitions": Counter()},
                )
                count["eligible"] += values["eligible"]
                count["changed_city"] += values["changed_city"]
                count["method_transitions"].update(values["method_transitions"])
            print(variant, record["block"], result["countries"], flush=True)
        reader = Cells(tables)
        named = [
            r
            for r in named_checks(
                Comparison(Cells(base["tables"]), {}, radius, reader), inputs
            )
            if h3.cell_to_parent(h3.latlng_to_cell(r["latitude"], r["longitude"], 8), 3)
            in roots
        ]
        if not all(r["passed"] for r in named):
            raise ValueError("Stored pilot named checks failed")
        reports[variant] = {
            "tables": tables,
            "countries": counts,
            "named": named,
            "stored_cells": sum(r["rows"] for r in tables),
        }
        write_json(output / "report.json", reports)
    # Exercise actual publication joins on the smallest pilot place catalogue.
    chosen = min(
        (
            r
            for r in base["tables"]
            if r["kind"] == "places" and r["country"] in engines
        ),
        key=lambda r: r["rows"],
    )
    reports["catalogue"] = places(
        workspace, output / "catalogue", {"tables": [chosen]}, normalized, inputs, urban
    )
    reports["catalogue_integrity"] = reference_checks(reports["catalogue"])
    if any(reports["catalogue_integrity"].values()):
        raise ValueError("Pilot catalogue has invalid normalization references")
    reports["scope"] = "Probe blocks only; transitions are not complete-country counts"
    write_json(output / "report.json", reports)


if __name__ == "__main__":
    main()

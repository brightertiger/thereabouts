"""Evaluate only development rows while tuning; never selects holdout rows."""

import argparse
import csv
from pathlib import Path

import h3

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import write_json
from build_data.golden.inputs import discover
from build_data.golden.reader import Cells
from build_data.normalize_cells.base import load
from build_data.normalize_cells.score import grade
from build_data.reconcile.common import Row, connect, unpack

from .engine import Engine
from .evaluate import Comparison
from .urban import Urban


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--points", type=Path, default=Path("eval/city_points/points.csv")
    )
    args = parser.parse_args()
    if not args.points.exists():
        print("Development points unavailable", flush=True)
        return
    with args.points.open(newline="", encoding="utf-8") as stream:
        selected = [r for r in csv.DictReader(stream) if r["split"] == "dev"]
    workspace = Workspace(args.data_dir.resolve())
    inputs = discover(workspace)
    normalized = read_json(workspace.root / "city_normalized/manifest.json")
    base = load(workspace, inputs)[1]
    urban = Urban(normalized["ghsl"]["partitions"])
    cells = [
        h3.latlng_to_cell(float(r["latitude"]), float(r["longitude"]), 8)
        for r in selected
    ]
    engines = {
        cc: Engine(
            Path(report["index"]["path"]),
            inputs.paths[cc],
            urban,
            normalized["policy"],
            (Path(inputs.land["path"]), inputs.policy["offshore_m"]),
        )
        for cc, report in normalized["countries"].items()
        if cc in {r["country_code"] for r in selected}
    }
    reports: dict[str, Row] = {}
    for radius in [False, True]:
        before, after = Comparison(Cells(base["tables"]), engines, radius).query(cells)
        names: dict[str, Row] = {}
        for cc in sorted(
            {
                r["country_id"].removeprefix("country:")
                for r in [*before, *after]
                if r.get("country_id")
            }
        ):
            db = connect(inputs.paths[cc], readonly=True)
            try:
                for identity in {
                    r["city_id"] for r in [*before, *after] if r.get("city_id")
                }:
                    row = db.execute(
                        "SELECT data FROM entities WHERE id=?", (identity,)
                    ).fetchone()
                    if row:
                        names[identity] = unpack(row[0])
                        names[identity]["wikidata_ids"] = []
            finally:
                db.close()
        reports["on" if radius else "off"] = {
            "before": grade(selected, cells, before, names),
            "after": grade(selected, cells, after, names),
            "normalized_countries": sorted(engines),
        }
    write_json(workspace.work / "v2-dev.json", reports)
    for name, report in reports.items():
        print(
            name,
            report["before"]["counts"],
            "->",
            report["after"]["counts"],
            flush=True,
        )


if __name__ == "__main__":
    main()

"""Score a golden snapshot against frozen, split-labelled hand-checked points."""

import csv
from pathlib import Path

import duckdb
import h3

from pipeline.config.loader import load
from pipeline.engines.artifacts import read_json
from pipeline.engines.cells.reader import Cells
from pipeline.engines.cities.evaluate import lookup
from pipeline.engines.normalize_cells.score import grade
from pipeline.engines.reconcile.common import Row
from pipeline.runtime.jsonio import digest, sha256_file, write_json
from pipeline.runtime.paths import located


def score(
    root: Path, manifest_path: Path, points: Path, split: str, receipt: Path
) -> Row:
    if split not in {"dev", "holdout"}:
        raise ValueError("Evaluation split must be dev or holdout")
    if not points.exists():
        result: Row = {"status": "unavailable", "points": points.name, "split": split}
        print(result, flush=True)
        return result
    manifest = read_json(manifest_path)
    tables = [{**r, "path": str(located(root, r["path"]))} for r in manifest["tables"]]
    if split == "holdout" and not manifest.get("completed"):
        raise ValueError(
            "Holdout may only be scored on the final verified world output"
        )
    identity = digest(
        {"golden": manifest, "points": sha256_file(points), "split": split}
    )
    if split == "holdout" and receipt.exists():
        previous = read_json(receipt)
        if previous.get("identity") != identity:
            raise ValueError(
                "Holdout already scored; refusing evaluation on a changed dataset"
            )
        print(previous["counts"], flush=True)
        return previous
    with points.open(newline="", encoding="utf-8") as stream:
        selected = [r for r in csv.DictReader(stream) if r["split"] == split]
    cells = [
        h3.latlng_to_cell(float(r["latitude"]), float(r["longitude"]), 8)
        for r in selected
    ]
    answers = lookup(Cells(tables), cells)
    ids = sorted({r["city_id"] for r in answers if r.get("city_id")})
    db = duckdb.connect()
    db.execute("SET memory_limit=?", [load().resources.duckdb_memory])
    try:
        db.read_parquet(
            [r["path"] for r in tables if r["kind"] == "places"]
        ).create_view("places")
        found = db.execute(
            "SELECT place_id,name,country_code,geonames_id,wikidata_ids FROM places "
            "WHERE place_id IN (SELECT unnest(?))",
            [ids],
        ).fetchall()
        names = {
            i: {"name": n, "country_code": c, "geonames_id": g, "wikidata_ids": w}
            for i, n, c, g, w in found
        }
    finally:
        db.close()
    result = {
        "identity": identity,
        "split": split,
        "points_sha256": sha256_file(points),
        **grade(selected, cells, answers, names),
    }
    write_json(receipt, result)
    print(result["counts"], flush=True)
    return result

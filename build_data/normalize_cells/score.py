"""Score a golden snapshot against frozen, split-labelled hand-checked points."""

import csv
import unicodedata
from collections import Counter
from pathlib import Path

import duckdb
import h3

from build_data.acquire.artifacts import read_json
from build_data.acquire.io import sha256_file, write_json
from build_data.cities.evaluate import lookup
from build_data.golden import paths as data_paths
from build_data.golden.reader import Cells
from build_data.reconcile.common import Row


def normalized_name(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFC", value or "").casefold().split())


def score(output: Path, points: Path, split: str) -> Row:
    if not points.exists():
        result: Row = {"status": "unavailable", "points": str(points), "split": split}
        print(result, flush=True)
        return result
    manifest = data_paths.manifest(output / "manifest.json")
    data_root = (output / manifest.get("data_root", ".")).resolve()
    if split == "holdout" and not manifest.get("completed"):
        raise ValueError(
            "Holdout may only be scored on the final verified world output"
        )
    receipt = output / f"{split}-score.json"
    identity = data_paths.digest(
        {"golden": manifest, "points": sha256_file(points), "split": split}, data_root
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
    answers = lookup(Cells(manifest["tables"]), cells)
    ids = sorted({r["city_id"] for r in answers if r.get("city_id")})
    db = duckdb.connect()
    db.execute("SET memory_limit='256MB'")
    try:
        db.read_parquet(
            [r["path"] for r in manifest["tables"] if r["kind"] == "places"]
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


def grade(
    selected: list[dict[str, str]],
    cells: list[str],
    answers: list[Row],
    names: dict[str, Row],
) -> Row:
    counts: Counter[str] = Counter()
    groups: dict[str, Counter[str]] = {}
    rows = []
    for point, cell, answer in zip(selected, cells, answers, strict=True):
        actual = names.get(answer.get("city_id") or "", {})
        expected_id = point.get("expected_city_id") or point.get("expected_place_id")
        expected = (
            point.get("expected_name")
            or point.get("expected_city")
            or point.get("expected_settlement")
        )
        if not expected_id and not expected:
            raise ValueError("Evaluation row needs expected_city_id or expected_city")
        country = point.get("country_code") or point.get("country")
        accepted = {
            normalized_name(n)
            for n in [expected or "", *point.get("accepted_names", "").split("|")]
            if n
        }
        passed = bool(
            (expected_id and answer.get("city_id") == expected_id)
            or (
                point.get("expected_geonames_id")
                and actual.get("geonames_id") == point["expected_geonames_id"]
            )
            or (
                point.get("expected_wikidata")
                and point["expected_wikidata"] in actual.get("wikidata_ids", [])
            )
            or normalized_name(actual.get("name")) in accepted
        )
        passed = passed and (
            not country or answer.get("country_id") == "country:" + country
        )
        if point.get("ambiguous", "").casefold() not in {"yes", "true", "1"}:
            counts["unambiguous_total"] += 1
            counts["unambiguous_correct"] += int(passed)
        group = point.get("category") or point.get("group") or "unspecified"
        counts["total"] += 1
        counts["correct"] += int(passed)
        counts["covered"] += int(bool(answer.get("city_id")))
        counts["distant"] += int(answer.get("city_method") == "rural_nearest_distant")
        group_counts = groups.setdefault(group, Counter())
        group_counts["total"] += 1
        group_counts["correct"] += int(passed)
        rows.append(
            {
                "point": point,
                "h3": cell,
                "answer": {**answer, **actual},
                "passed": passed,
            }
        )
    return {
        "counts": dict(counts),
        "groups": {k: dict(v) for k, v in groups.items()},
        "rows": rows,
    }

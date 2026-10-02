"""Split isolation and one-time holdout scoring on tiny published tables."""

import csv
from pathlib import Path

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from build_data.acquire.io import write_json
from build_data.golden_v2.score import normalized_name, score


def test_holdout_requires_final_snapshot_and_cannot_be_retuned(tmp_path: Path) -> None:
    points = tmp_path / "points.csv"
    fields = [
        "id",
        "latitude",
        "longitude",
        "expected_name",
        "accepted_names",
        "country_code",
        "split",
    ]
    with points.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for split, name in [("dev", "Wrong on purpose"), ("holdout", "City")]:
            writer.writerow(
                dict(
                    id=split,
                    latitude=0,
                    longitude=0,
                    expected_name=name,
                    accepted_names="",
                    country_code="ZZ",
                    split=split,
                )
            )
    cell = h3.latlng_to_cell(0, 0, 8)
    cell_path, place_path = tmp_path / "cell.parquet", tmp_path / "place.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "h3": cell,
                    "h3_uint64": int(cell, 16),
                    "h3_resolution": 8,
                    "country_id": "country:ZZ",
                    "city_id": "city:one",
                    "city_method": "city_polygon",
                }
            ]
        ),
        cell_path,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "place_id": "city:one",
                    "name": "City",
                    "country_code": "ZZ",
                    "geonames_id": "1",
                    "wikidata_ids": ["Q1"],
                }
            ]
        ),
        place_path,
    )
    manifest = {
        "completed": False,
        "tables": [
            {
                "kind": "cells",
                "block": h3.cell_to_parent(cell, 3),
                "path": str(cell_path),
            },
            {"kind": "places", "path": str(place_path)},
        ],
    }
    write_json(tmp_path / "manifest.json", manifest)
    with pytest.raises(ValueError, match="final verified"):
        score(tmp_path, points, "holdout")
    assert score(tmp_path, points, "dev")["counts"]["correct"] == 0
    manifest["completed"] = True
    write_json(tmp_path / "manifest.json", manifest)
    result = score(tmp_path, points, "holdout")
    assert result["counts"]["total"] == result["counts"]["correct"] == 1
    assert score(tmp_path, points, "holdout") == result
    manifest["revision"] = "retuned"
    write_json(tmp_path / "manifest.json", manifest)
    with pytest.raises(ValueError, match="already scored"):
        score(tmp_path, points, "holdout")


def test_name_matching_preserves_suffixes_punctuation_and_accents() -> None:
    assert normalized_name("  DELHI\tCity ") == "delhi city"
    assert normalized_name("Café") == normalized_name("Cafe\u0301")
    assert normalized_name("Delhi") != normalized_name("Delhi City")
    assert normalized_name("Café") != normalized_name("Cafe")
    assert normalized_name("New-York") != normalized_name("New York")

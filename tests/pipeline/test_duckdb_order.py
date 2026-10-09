"""Writer queries keep input order, so DuckDB thread counts never change bytes."""

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.config.engines import EngineLimits
from pipeline.config.schema import Resources
from pipeline.engines import query
from pipeline.engines.normalize_cells import tables
from pipeline.engines.reconcile import inputs

SOURCES = (
    "geonames_places",
    "overture_places",
    "overture_areas",
    "geoboundaries_areas",
    "geonames_names",
)


def provenance(parent: str | None) -> str:
    hierarchy = [{"division_id": parent, "subtype": "country"}] if parent else []
    return json.dumps({"upstream": {"hierarchies": [hierarchy]}})


def write(root: Path, name: str, rows: list[dict[str, Any]], files: int) -> list[str]:
    paths = []
    for index in range(files):
        path = root / f"{name}-{index:02d}.parquet"
        pq.write_table(
            pa.Table.from_pylist(rows[index::files]), path, row_group_size=1000
        )
        paths.append(str(path))
    return paths


def source_rows(prefix: str, count: int) -> list[dict[str, Any]]:
    rows = []
    for i in range(count):
        subtype = "dependency" if i % 97 == 0 else "locality"
        parent = f"{prefix}-country-{i % 2}" if subtype == "dependency" else None
        rows.append(
            {
                "source_id": f"{prefix}-{i}",
                "country_code": "ZZ" if i % 3 else "YY",
                "subtype": subtype,
                "language": "wkdt",
                "entity_source_id": f"geonames_places-{i}",
                "name": f"Place {i}",
                "name_en": None,
                "provenance": provenance(parent),
            }
        )
    for index in range(2):
        rows.append(
            {
                "source_id": f"{prefix}-country-{index}",
                "country_code": f"P{index}",
                "subtype": "country",
                "language": "wkdt",
                "entity_source_id": "",
                "name": f"Parent {index}",
                "name_en": None,
                "provenance": provenance(None),
            }
        )
    return rows


def extracted(
    root: Path, paths: dict[str, list[str]], threads: int
) -> tuple[dict[str, Any], list[bytes]]:
    work = root / f"threads-{threads}-{len(list(root.glob('threads-*')))}"
    limits = EngineLimits()
    db = inputs.query_engine(
        paths, work, Resources(duckdb_threads=threads, duckdb_memory="256MB"), limits
    )
    policy: dict[str, Any] = {"sovereigns": {}}
    try:
        inputs.sovereigns(db, policy)
        outputs = inputs.extract(db, "ZZ", work / "ZZ", limits)
    finally:
        db.close()
    return policy["sovereigns"], [path.read_bytes() for path in outputs]


def test_extraction_and_sovereigns_ignore_thread_count(tmp_path: Path) -> None:
    paths = {
        name: write(tmp_path, name, source_rows(name, 60_000), 4) for name in SOURCES
    }
    expected = extracted(tmp_path, paths, 1)
    assert expected[0]["YY"] == ["P0", "Parent 0"]
    for _ in range(3):
        assert extracted(tmp_path, paths, 4) == expected


def joined(root: Path, threads: int, run: int) -> bytes:
    db = query.connect(
        root / f"spill-{threads}-{run}",
        Resources(duckdb_threads=threads, duckdb_memory="256MB"),
        EngineLimits(),
    )
    output = root / f"places-{threads}-{run}.parquet"
    try:
        tables.places(
            db,
            root / "base.parquet",
            root / "mapping.parquet",
            root / "cities.parquet",
            output,
            2048,
        )
    finally:
        db.close()
    return output.read_bytes()


def test_place_normalization_ignores_thread_count(tmp_path: Path) -> None:
    count = 200_000
    pq.write_table(
        pa.table(
            {
                "place_id": [f"p{i}" for i in range(count)],
                "name": [f"Place {i}" for i in range(count)],
                "role": ["city" if i % 5 else "locality" for i in range(count)],
                "settlement_class": [None] * count,
            }
        ),
        tmp_path / "base.parquet",
        row_group_size=5000,
    )
    pq.write_table(
        pa.table(
            {
                "place_id": [f"p{i}" for i in range(0, count, 2)],
                "city_id": [f"p{i - i % 10}" for i in range(0, count, 2)],
                "method": ["fixture"] * (count // 2),
            }
        ),
        tmp_path / "mapping.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "place_id": [f"p{i}" for i in range(0, count, 10)],
                "name": [f"City {i}" for i in range(0, count, 10)],
                "kind": ["city"] * (count // 10),
            }
        ),
        tmp_path / "cities.parquet",
    )
    expected = joined(tmp_path, 1, 0)
    assert all(joined(tmp_path, 4, run) == expected for run in range(3))

"""Spatial lookup joins keep duplicates, pending coverage, and source disagreements."""

from pathlib import Path

import duckdb
import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.config import load
from pipeline.config.engines import EngineLimits
from pipeline.config.schema import H3
from pipeline.engines.cells import joins
from pipeline.engines.cells.metrics import measure
from pipeline.engines.cells.reader import Cells
from pipeline.engines.cells.schemas import CELLS
from pipeline.engines.store.codec import Row


def table(root: Path, cell: str, rows: list[Row]) -> Row:
    path = root / f"{cell}.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=CELLS), path)
    return {"path": str(path), "kind": "cells", "block": cell, "rows": len(rows)}


def test_partial_join_preserves_cardinality_country_and_fills_new_coverage(
    tmp_path: Path,
) -> None:
    cell = h3.latlng_to_cell(10, 10, 8)
    root = h3.cell_to_parent(cell, 3)
    ocean = h3.latlng_to_cell(0, -140, 8)
    pending = h3.latlng_to_cell(40, 40, 8)
    cells = [
        table(
            tmp_path,
            root,
            [
                {
                    "h3": root,
                    "h3_uint64": int(root, 16),
                    "h3_resolution": 3,
                    "country_id": "country:ZZ",
                    "state_id": "state:Z",
                    "city_id": "city:Z",
                    "city_method": "area",
                    "land_method": "land",
                }
            ],
        ),
        table(tmp_path, h3.cell_to_parent(ocean, 3), []),
    ]
    source = pa.table(
        {
            "country_code": ["YY", "ZZ", "ZZ", "ZZ", "ZZ"],
            "h3_uint64": pa.array(
                [int(c, 16) if c else None for c in [cell, cell, ocean, pending, None]],
                type=pa.uint64(),
            ),
        }
    )
    with duckdb.connect() as db:
        db.register("source", source)
        joins.assignments(db, joins.prepare(db, cells), H3())
        rows = db.sql(
            "SELECT s.country_code,a.cell_country_code,"
            "coalesce(a.cell_status,'unlocated') AS status "
            "FROM source s LEFT JOIN assignments a USING(h3_uint64)"
        ).fetchall()
        assert sorted(r[2] for r in rows) == [
            "ineligible",
            "matched",
            "matched",
            "pending",
            "unlocated",
        ]
        assert sum(a != b for a, b, _ in rows if a and b) == 1
        cells.append(table(tmp_path, h3.cell_to_parent(pending, 3), []))
        joins.assignments(db, joins.prepare(db, cells), H3())
        assert db.sql(
            "SELECT count(*) FROM assignments WHERE cell_status='pending'"
        ).fetchone() == (0,)
    reader = Cells(cells, grid=H3(), limits=EngineLimits())
    assert reader.lookup(cell)["city_id"] == "city:Z"
    assert reader.lookup(ocean)["cell_status"] == "ineligible"
    with pytest.raises(ValueError, match="resolution 8"):
        reader.lookup(root)
    places = tmp_path / "places.parquet"
    pq.write_table(
        pa.table(
            {
                "place_id": ["country:ZZ", "state:Z", "city:Z"],
                "parent_id": [None, "country:ZZ", "state:Z"],
                "sovereign_id": ["country:ZZ"] * 3,
            }
        ),
        places,
    )
    config = load()
    metrics = measure(
        tmp_path,
        [{"path": str(places), "kind": "places"}],
        cells,
        config.resources,
        config.engines.limits,
        grid=config.h3,
    )
    assert metrics["represented_r8_centres"]["eligible"] == 7**5
    assert metrics["represented_r8_centres"]["city"] == 7**5
    assert metrics["missing_cell_place_ids"] == metrics["duplicate_place_ids"] == 0

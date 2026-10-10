"""Configured grids and cache budgets reach row and columnar ancestor readers."""

from pathlib import Path

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.config.engines import EngineLimits
from pipeline.config.schema import H3
from pipeline.engines.cells.compaction import compact
from pipeline.engines.cells.reader import Cells, interval
from pipeline.engines.cities.evaluate import lookup
from pipeline.engines.store.database import connect


def test_nondefault_grid_drives_compaction_intervals_and_both_readers(
    tmp_path: Path,
) -> None:
    grid = H3(block_resolution=3, cell_resolution=5)
    root = h3.latlng_to_cell(0, 0, grid.block_resolution)
    descendants = sorted(h3.cell_to_children(root, grid.cell_resolution))
    cells = np.array([int(cell, 16) for cell in descendants], dtype=np.uint64)
    stored, labels = compact(cells, np.ones(len(cells), dtype=np.uint64), grid=grid)
    assert stored.tolist() == [int(root, 16)] and labels.tolist() == [1]
    low, high = interval(int(root, 16), grid.block_resolution, grid.cell_resolution)
    assert all(low <= int(cell) <= high for cell in cells)
    path = tmp_path / "cells.parquet"
    pq.write_table(
        pa.table(
            {
                "h3": [root],
                "h3_uint64": pa.array([int(root, 16)], type=pa.uint64()),
                "h3_resolution": [grid.block_resolution],
                "country_id": ["country:ZZ"],
            }
        ),
        path,
    )
    reader = Cells(
        [{"kind": "cells", "block": root, "path": str(path)}],
        EngineLimits(reader_cache_entries=1),
        grid=grid,
    )
    expected = [reader.lookup(cell) for cell in descendants]
    assert lookup(reader, descendants) == expected
    assert all(row["country_id"] == "country:ZZ" for row in expected)
    with connect(tmp_path / "index.sqlite", cache_kib=73) as db:
        assert db.execute("PRAGMA cache_size").fetchone() == (-73,)

"""Block indexing updates country dependencies, including explicit ocean blocks."""

import json
import sqlite3
from pathlib import Path

from h3.api import basic_int as h3

from pipeline.config import load
from pipeline.config.policies import reconcile
from pipeline.engines.cells.inventory import index


def test_changed_country_dependencies_and_ocean_blocks(tmp_path: Path) -> None:
    path = tmp_path / "blocks.sqlite3"
    root = h3.int_to_str(h3.latlng_to_cell(0, 0, 3))
    ocean = h3.int_to_str(h3.latlng_to_cell(0, -140, 3))
    for cc in ("AA", "BB"):
        index(
            path,
            {"bounds": [[cc, -5, -5, 5, 5]]},
            reconcile(),
            load().h3,
            [root, ocean],
            load().engines.limits,
        )
        db = sqlite3.connect(path)
        try:
            rows = dict(db.execute("SELECT root,countries FROM blocks"))
            assert json.loads(rows[root]) == [cc]
            assert json.loads(rows[ocean]) == []
        finally:
            db.close()

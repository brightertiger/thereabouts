"""Configure bounded analytical joins in the current workspace."""

from pathlib import Path

import duckdb

from pipeline.config.engines import EngineLimits
from pipeline.config.schema import Resources


def connect(
    work: Path, resources: Resources, limits: EngineLimits
) -> duckdb.DuckDBPyConnection:
    work.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect()
    db.execute("SET memory_limit=?", [resources.duckdb_memory])
    db.execute("SET threads=?", [resources.duckdb_threads])
    db.execute("SET preserve_insertion_order=false")
    db.execute("SET temp_directory=?", [str(work)])
    db.execute("SET max_temp_directory_size=?", [f"{limits.duckdb_spill_bytes}B"])
    return db

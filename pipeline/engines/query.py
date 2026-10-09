"""One configured DuckDB connection for bounded analytical joins."""

from pathlib import Path

import duckdb

from pipeline.config.engines import EngineLimits
from pipeline.config.schema import Resources


def connection(
    resources: Resources,
    spill_bytes: int,
    *,
    spill: Path | None = None,
    ordered: bool = True,
) -> duckdb.DuckDBPyConnection:
    """Bounded memory and threads, and spill capped at `spill_bytes`.

    Spill goes to `spill`, or DuckDB's default directory when it is None.
    `ordered=False` lets DuckDB drop insertion order; only queries that order
    their own output may use it.
    """
    db = duckdb.connect()
    db.execute("SET memory_limit=?", [resources.duckdb_memory])
    db.execute("SET threads=?", [resources.duckdb_threads])
    if not ordered:
        db.execute("SET preserve_insertion_order=false")
    if spill is not None:
        db.execute("SET temp_directory=?", [str(spill)])
    db.execute("SET max_temp_directory_size=?", [f"{spill_bytes}B"])
    return db


def connect(
    work: Path, resources: Resources, limits: EngineLimits
) -> duckdb.DuckDBPyConnection:
    """The stages' unordered join connection, spilling under `work`."""
    work.mkdir(parents=True, exist_ok=True)
    return connection(resources, limits.duckdb_spill_bytes, spill=work, ordered=False)

"""Every DuckDB site keeps its settings through the one connection helper."""

from pathlib import Path

import duckdb

from pipeline.config.engines import EngineLimits
from pipeline.config.schema import Resources
from pipeline.engines.query import connect, connection

SETTINGS = (
    "memory_limit",
    "threads",
    "preserve_insertion_order",
    "temp_directory",
    "max_temp_directory_size",
)


def settings(db: duckdb.DuckDBPyConnection) -> dict[str, object]:
    return {
        name: db.execute("SELECT current_setting(?)", [name]).fetchone()
        for name in SETTINGS
    }


def old(statements: list[tuple[str, object]]) -> dict[str, object]:
    """The inline sequence a site ran before the helper existed."""
    db = duckdb.connect()
    try:
        for name, value in statements:
            db.execute(f"SET {name}=?", [value])
        return settings(db)
    finally:
        db.close()


def test_each_site_keeps_its_settings_and_gains_a_spill_cap(tmp_path: Path) -> None:
    resources = Resources(duckdb_memory="256MB", duckdb_threads=2)
    limits = EngineLimits(duckdb_spill_bytes=123_000_000)
    base: list[tuple[str, object]] = [("memory_limit", "256MB"), ("threads", 2)]
    cap = ("max_temp_directory_size", "123000000B")
    spill = tmp_path / "spill"
    unordered = ("preserve_insertion_order", False)
    cases = {
        # engines/query.connect and reconcile/inputs.query_engine
        "unordered": (
            connection(resources, 123_000_000, spill=spill, ordered=False),
            [*base, unordered, ("temp_directory", str(spill)), cap],
        ),
        # cells/metrics.measure
        "ordered": (
            connection(resources, 123_000_000, spill=spill),
            [*base, ("temp_directory", str(spill)), cap],
        ),
        # cells/inventory, normalize_cells/references, stages/engine_data: the
        # same memory and threads, now with a spill cap they lacked.
        "default spill": (connection(resources, 123_000_000), [*base, cap]),
    }
    for name, (db, statements) in cases.items():
        try:
            assert settings(db) == old(statements), name
        finally:
            db.close()
    work = tmp_path / "work"
    db = connect(work, resources, limits)
    try:
        assert work.is_dir()
        assert settings(db) == old(
            [*base, unordered, ("temp_directory", str(work)), cap]
        )
    finally:
        db.close()

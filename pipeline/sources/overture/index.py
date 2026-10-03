"""Build a disk-backed division-parent cache before any area normalization."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pyarrow.parquet as pq

from pipeline.runtime.jsonio import atomic_output
from pipeline.sources.contract import SourceContext


def build_index(ctx: SourceContext) -> Path:
    target = ctx.work / ctx.unit.inputs_hash / "entities.sqlite3"
    ctx.ensure(target)
    options = ctx.settings.options
    reservation = int(options["index_bytes"])
    ctx.runtime.guard.admit(reservation)
    written = 0
    try:
        with (
            atomic_output(target) as temporary,
            closing(sqlite3.connect(temporary)) as db,
        ):
            db.execute(f"PRAGMA cache_size=-{int(options['sqlite_cache_kib'])}")
            db.execute("PRAGMA temp_store=FILE")
            db.execute(
                "CREATE TABLE entities (id TEXT PRIMARY KEY, parent TEXT) WITHOUT ROWID"
            )
            for pin in ctx.pin.files:
                if pin.metadata["type"] != "division":
                    continue
                with db, pq.ParquetFile(ctx.input(pin.name)) as parquet:
                    for batch in parquet.iter_batches(
                        batch_size=int(options["index_batch_rows"]),
                        columns=["id", "parent_division_id"],
                        use_threads=False,
                    ):
                        ctx.runtime.guard.admit()
                        db.executemany(
                            "INSERT INTO entities VALUES (?,?)",
                            (
                                (row["id"], row["parent_division_id"])
                                for row in batch.to_pylist()
                            ),
                        )
                if temporary.stat().st_size > reservation:
                    raise ValueError("Overture index exceeds configured index_bytes")
            if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise ValueError("Overture index integrity check failed")
        written = target.stat().st_size
        return target
    finally:
        ctx.runtime.guard.release(reservation, written_bytes=written)

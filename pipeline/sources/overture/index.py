"""Build a disk-backed division-parent cache before any area normalization."""

from pathlib import Path

import pyarrow.parquet as pq

from pipeline.sources.contract import SourceContext
from pipeline.sources.shared.scratch import scratch_index


def build_index(ctx: SourceContext) -> Path:
    options = ctx.settings.options
    with scratch_index(
        ctx,
        "entities.sqlite3",
        int(options["index_bytes"]),
        label="Overture",
        cache_kib=int(options["sqlite_cache_kib"]),
    ) as index:
        db = index.db
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
                    ctx.guard.admit()
                    db.executemany(
                        "INSERT INTO entities VALUES (?,?)",
                        (
                            (row["id"], row["parent_division_id"])
                            for row in batch.to_pylist()
                        ),
                    )
            index.check_size()
    return index.path

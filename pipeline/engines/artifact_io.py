"""Atomic geographic artifacts with root-relative records and bounded row batches."""

from collections.abc import Iterable, Iterator
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

# Re-exported for Package G's modules until they import pipeline.files.
from pipeline.files import file_record as file_record
from pipeline.runtime.jsonio import atomic_output

from .reconcile.common import Row


def batches(rows: Iterable[Row], size: int) -> Iterator[list[Row]]:
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def parquet(
    root: Path, path: Path, rows: Iterable[Row], schema: pa.Schema, batch_rows: int
) -> Row:
    count = 0
    with atomic_output(path) as temporary:
        with pq.ParquetWriter(temporary, schema, compression="zstd") as writer:
            for group in batches(rows, batch_rows):
                writer.write_table(pa.Table.from_pylist(group, schema=schema))
                count += len(group)
        if pq.read_metadata(temporary).num_rows != count:
            raise ValueError("Parquet row count changed during publication")
    return {**file_record(root, path), "rows": count}

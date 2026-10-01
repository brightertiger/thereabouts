"""Bounded Parquet publication shared by every source adapter."""

from collections.abc import Iterable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .io import atomic_output
from .schemas import MAX_BATCH_BYTES, MAX_PARTITION_BYTES, SCHEMAS, Kind, validate_table


def validate_parquet(path: Path, kind: Kind) -> None:
    """Validate a single bounded partition, including decoded data and geometry."""
    if path.stat().st_size > MAX_PARTITION_BYTES:
        raise ValueError("Parquet partition exceeds 128 MB on disk")
    with pq.ParquetFile(path) as file:
        if not file.schema_arrow.equals(SCHEMAS[kind], check_metadata=False):
            raise ValueError(f"Expected {kind} schema")
        # Check physical row-group sizes before allocating decoded data.
        if (
            sum(
                file.metadata.row_group(i).total_byte_size
                for i in range(file.num_row_groups)
            )
            > MAX_PARTITION_BYTES
        ):
            raise ValueError("Parquet partition exceeds 128 MB uncompressed")
        decoded = 0
        for index in range(file.num_row_groups):
            group = file.metadata.row_group(index)
            if group.total_byte_size > MAX_BATCH_BYTES:
                raise ValueError("Row group exceeds 32 MB uncompressed")
            if any(
                encoding not in ("PLAIN", "RLE")
                for column in range(group.num_columns)
                for encoding in group.column(column).encodings
            ):
                raise ValueError("Use plain values without dictionary/delta expansion")
            for batch in file.iter_batches(batch_size=1024, row_groups=[index]):
                validate_table(batch, kind)
                decoded += batch.nbytes
                if decoded > MAX_PARTITION_BYTES:
                    raise ValueError("Decoded partition exceeds 128 MB")


def write_partition(
    path: Path, kind: Kind, batches: Iterable[pa.Table | pa.RecordBatch]
) -> None:
    """Validate and publish one partition; callers rotate at the byte limits."""
    with (
        atomic_output(path, lambda p: validate_parquet(p, kind)) as temporary,
        pq.ParquetWriter(
            temporary, SCHEMAS[kind], compression="zstd", use_dictionary=False
        ) as writer,
    ):
        size = 0
        for batch in batches:
            validate_table(batch, kind)
            size += batch.nbytes
            if size > MAX_PARTITION_BYTES:
                raise ValueError("Partition exceeds 128 MB; rotate to another part")
            # Row groups never span incoming byte-bounded batches.
            rows = max(1, min(1024, batch.num_rows))
            writer.write_table(
                pa.Table.from_batches([batch])
                if isinstance(batch, pa.RecordBatch)
                else batch,
                row_group_size=rows,
            )

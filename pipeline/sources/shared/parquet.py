"""Bounded source Parquet files with plain encoding and validated publication."""

from collections.abc import Iterable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.config.sources import SourceLimits
from pipeline.runtime.jsonio import atomic_output

from .schemas import SCHEMAS, Kind, validate_table


def validate_parquet(path: Path, kind: Kind, source: str, limits: SourceLimits) -> None:
    if path.stat().st_size > limits.parquet_bytes:
        raise ValueError("Encoded Parquet exceeds the configured partition limit")
    with pq.ParquetFile(path) as file:
        if not file.schema_arrow.equals(SCHEMAS[kind], check_metadata=False):
            raise ValueError(f"Expected {kind} schema")
        decoded = 0
        for index in range(file.num_row_groups):
            group = file.metadata.row_group(index)
            if group.total_byte_size > limits.row_group_bytes:
                raise ValueError("Row group exceeds the configured batch limit")
            if any(
                encoding not in ("PLAIN", "RLE")
                for column in range(group.num_columns)
                for encoding in group.column(column).encodings
            ):
                raise ValueError("Use plain values without dictionary/delta expansion")
            for batch in file.iter_batches(
                batch_size=limits.batch_rows, row_groups=[index]
            ):
                validate_table(batch, kind, source, limits)
                decoded += batch.nbytes
                if decoded > limits.parquet_bytes:
                    raise ValueError("Decoded partition exceeds the configured limit")


def write_partition(
    path: Path,
    kind: Kind,
    source: str,
    limits: SourceLimits,
    batches: Iterable[pa.Table],
) -> None:
    with atomic_output(path) as temporary:
        with pq.ParquetWriter(
            temporary, SCHEMAS[kind], compression="zstd", use_dictionary=False
        ) as writer:
            size = 0
            for batch in batches:
                validate_table(batch, kind, source, limits)
                size += batch.nbytes
                if size > limits.parquet_bytes:
                    raise ValueError("Partition exceeds the configured limit")
                writer.write_table(batch, row_group_size=limits.batch_rows)
        validate_parquet(temporary, kind, source, limits)

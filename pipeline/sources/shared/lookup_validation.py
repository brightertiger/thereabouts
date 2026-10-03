"""Batch validation for large lookup tables without per-field Python dispatch."""

from collections.abc import Callable
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from .lookup_schemas import validate_lookup


def validate_lookup_batch(
    batch: pa.RecordBatch,
    kind: str,
    sources: tuple[str, ...],
    provenance: Callable[[dict[str, object]], None],
    max_row_bytes: int,
) -> None:
    for field in batch.schema:
        if pa.types.is_string(field.type):
            blank = pc.equal(
                pc.utf8_trim_whitespace(batch.column(field.name)), pa.scalar("")
            )
            if pc.any(blank).as_py():
                raise ValueError(f"Use null for missing strings: {field.name}")
    rows: list[dict[str, Any]] = batch.to_pylist()
    for index, row in enumerate(rows):
        # A row cannot exceed the bound if the entire batch is smaller. Only
        # geometry/XML-heavy batches need individual Arrow byte measurements.
        if (
            batch.nbytes > max_row_bytes
            and batch.slice(index, 1).nbytes > max_row_bytes
        ):
            raise ValueError("Row exceeds 8 MB")
        if row["source"] not in sources:
            raise ValueError("Unknown source")
        provenance(row)
        country = row.get("country_code")
        if country is not None and (
            len(country) != 2
            or not country.isascii()
            or not country.isalpha()
            or country != country.upper()
        ):
            raise ValueError("country_code must be uppercase ISO alpha-2 (or XK)")
        validate_lookup(row, kind)

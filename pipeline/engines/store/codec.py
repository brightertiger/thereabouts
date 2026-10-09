"""Canonical JSON, lossless zlib packing and name keys for artifact rows."""

from __future__ import annotations

import json
import unicodedata
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

Row = dict[str, Any]


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pack(value: Any) -> bytes:
    """Lossless source evidence compression; no names or provenance are dropped."""
    return zlib.compress(encode(value).encode("utf-8"), level=1)


def unpack(value: bytes | str) -> Row:
    result: Row = json.loads(
        zlib.decompress(value) if isinstance(value, bytes) else value
    )
    return result


def key(name: str | None) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", name or "").casefold() if c.isalnum()
    )


def rows(path: Path, batch_rows: int) -> Iterator[Row]:
    with pq.ParquetFile(path) as file:
        for batch in file.iter_batches(batch_size=batch_rows):
            yield from batch.to_pylist()

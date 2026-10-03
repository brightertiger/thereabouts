"""Bounded IO and reproducible policy inputs for reconciliation."""

from __future__ import annotations

import json
import sqlite3
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


def connect(
    path: Path,
    *,
    readonly: bool = False,
    cache_kib: int,
) -> sqlite3.Connection:
    db = sqlite3.connect(
        f"{path.absolute().as_uri()}?mode=ro&immutable=1" if readonly else str(path),
        uri=readonly,
    )
    db.execute(f"PRAGMA cache_size=-{cache_kib}")
    db.execute("PRAGMA temp_store=FILE")
    return db


def check_database(path: Path, cache_kib: int) -> None:
    db = connect(path, readonly=True, cache_kib=cache_kib)
    try:
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError(f"Invalid SQLite artifact: {path}")
    finally:
        db.close()

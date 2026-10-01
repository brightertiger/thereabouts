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

from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, sha256_file

Row = dict[str, Any]
POLICY_PATH = Path(__file__).with_name("policy.json")


def policy() -> Row:
    return read_json(POLICY_PATH)


def builder_hash() -> str:
    return fingerprint(
        {p.name: sha256_file(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    )


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


def rows(path: Path) -> Iterator[Row]:
    with pq.ParquetFile(path) as file:
        for batch in file.iter_batches(batch_size=512):
            yield from batch.to_pylist()


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    db = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro" if readonly else str(path), uri=readonly
    )
    db.execute("PRAGMA cache_size=-16384")
    db.execute("PRAGMA temp_store=FILE")
    return db


def check_database(path: Path) -> None:
    db = connect(path, readonly=True)
    try:
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError(f"Invalid SQLite artifact: {path}")
    finally:
        db.close()

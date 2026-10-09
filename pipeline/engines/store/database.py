"""Open and verify SQLite artifacts with bounded caches and file-backed temp tables."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pipeline.errors import ArtifactIntegrityError
from pipeline.files import sqlite_readonly


def connect(
    path: Path,
    *,
    readonly: bool = False,
    cache_kib: int,
) -> sqlite3.Connection:
    if readonly:
        db = sqlite_readonly(path, cache_kib)
    else:
        db = sqlite3.connect(str(path))
        db.execute(f"PRAGMA cache_size=-{cache_kib}")
    db.execute("PRAGMA temp_store=FILE")
    return db


def check_database(path: Path, cache_kib: int) -> None:
    db = connect(path, readonly=True, cache_kib=cache_kib)
    try:
        if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ArtifactIntegrityError(f"Invalid SQLite artifact: {path}")
    finally:
        db.close()

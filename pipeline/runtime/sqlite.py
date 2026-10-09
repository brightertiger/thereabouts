"""Read-only connections to immutable SQLite artifacts."""

import sqlite3
from pathlib import Path


def sqlite_readonly(
    path: Path, cache_kib: int | None = None, *, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Immutable mode skips locking and change detection, so open only files that
    no process writes any more."""
    db = sqlite3.connect(
        f"{path.absolute().as_uri()}?mode=ro&immutable=1",
        uri=True,
        check_same_thread=check_same_thread,
    )
    if cache_kib is not None:
        db.execute(f"PRAGMA cache_size=-{int(cache_kib)}")
    return db

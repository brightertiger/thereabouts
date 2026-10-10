"""Records of published local files, and read-only access to immutable SQLite."""

import sqlite3
from pathlib import Path
from typing import Any

from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.paths import relative


def file_record(root: Path, path: Path) -> dict[str, Any]:
    """A root-relative path with the size and SHA-256 of its current bytes."""
    return {
        "path": relative(root, path),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


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

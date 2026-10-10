"""Regenerable SQLite indexes in a unit's work directory, within a disk reservation."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pipeline.errors import ArtifactIntegrityError, ConfigError
from pipeline.runtime.jsonio import atomic_output
from pipeline.sources.contract import SourceContext


@dataclass(frozen=True)
class ScratchIndex:
    db: sqlite3.Connection
    # Published here only after the build and its check succeed.
    path: Path
    building: Path
    reservation: int
    label: str

    def check_size(self) -> None:
        if self.building.stat().st_size > self.reservation:
            raise ConfigError(f"{self.label} index exceeds configured index_bytes")


@contextmanager
def scratch_index(
    ctx: SourceContext,
    name: str,
    reservation: int,
    *,
    label: str,
    check: Literal["quick_check", "integrity_check"] = "quick_check",
    cache_kib: int | None = None,
) -> Iterator[ScratchIndex]:
    """Reserve disk, build `work/<source>/<inputs hash>/<name>`, check, publish.

    The body fills `index.db` and calls `index.check_size()` as it grows. The
    reservation is released with the published size, or nothing on failure.
    A `cache_kib` bounds the page cache and sends temporary tables to disk.
    """
    target = ctx.ensure(ctx.work / ctx.inputs_hash / name)
    ctx.guard.admit(reservation)
    written = 0
    try:
        with (
            atomic_output(target) as temporary,
            closing(sqlite3.connect(temporary)) as db,
        ):
            if cache_kib is not None:
                db.execute(f"PRAGMA cache_size=-{int(cache_kib)}")
                db.execute("PRAGMA temp_store=FILE")
            yield ScratchIndex(db, target, temporary, reservation, label)
            if db.execute(f"PRAGMA {check}").fetchone() != ("ok",):
                raise ArtifactIntegrityError(f"{label} index integrity check failed")
        written = target.stat().st_size
    finally:
        ctx.guard.release(reservation, written_bytes=written)

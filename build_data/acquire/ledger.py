"""SQLite completion records, shared safely by independent source processes."""

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .io import sha256_file


class Ledger:
    """Track verified units; a caller owns each (stage, unit_id) exclusively."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS units ("
                "stage TEXT NOT NULL, unit_id TEXT NOT NULL, "
                "inputs_hash TEXT NOT NULL, "
                "outputs TEXT NOT NULL, metadata TEXT NOT NULL, "
                "completed_at TEXT NOT NULL, "
                "PRIMARY KEY (stage, unit_id))"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def completed_outputs(
        self, stage: str, unit_id: str, inputs_hash: str
    ) -> tuple[Path, ...] | None:
        """Return verified paths, or None for changed, missing or corrupt work."""
        with self._connect() as db:
            row = cast(
                tuple[str] | None,
                db.execute(
                    "SELECT outputs FROM units WHERE stage=? AND unit_id=? "
                    "AND inputs_hash=?",
                    (stage, unit_id, inputs_hash),
                ).fetchone(),
            )
        if row is None:
            return None
        outputs = cast(list[dict[str, str | int]], json.loads(row[0]))
        paths: list[Path] = []
        for output in outputs:
            path = Path(str(output["path"]))
            try:
                if (
                    path.stat().st_size != output["size"]
                    or sha256_file(path) != output["sha256"]
                ):
                    return None
            except FileNotFoundError:
                return None
            paths.append(path)
        return tuple(paths)

    def is_complete(self, stage: str, unit_id: str, inputs_hash: str) -> bool:
        """Skip only a matching unit whose outputs still pass size/hash checks."""
        return self.completed_outputs(stage, unit_id, inputs_hash) is not None

    def complete(
        self,
        stage: str,
        unit_id: str,
        inputs_hash: str,
        outputs: Sequence[Path],
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        """Record already validated, atomically published outputs in one transaction."""
        records: list[dict[str, str | int]] = []
        for path in outputs:
            if path.name.endswith(".part") or not path.is_file():
                raise ValueError(f"Output has not been published: {path}")
            records.append(
                {
                    "path": str(path.resolve()),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        with self._connect() as db:
            db.execute(
                "INSERT INTO units VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(stage, unit_id) DO UPDATE SET "
                "inputs_hash=excluded.inputs_hash, outputs=excluded.outputs, "
                "metadata=excluded.metadata, completed_at=excluded.completed_at",
                (
                    stage,
                    unit_id,
                    inputs_hash,
                    json.dumps(records, sort_keys=True),
                    json.dumps(dict(metadata or {}), sort_keys=True, allow_nan=False),
                    datetime.now(UTC).isoformat(),
                ),
            )

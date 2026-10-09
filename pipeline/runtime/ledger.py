"""One ledger; read-only inspection never creates SQLite sidecar files."""

import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .jsonio import Object, encode
from .outputs import describe
from .records import Completion, Output, Recipe, outputs_from_json, recipe_from_json

UNITS_SQL = (
    "CREATE TABLE IF NOT EXISTS units (stage TEXT NOT NULL, unit_id TEXT NOT NULL, "
    "inputs_hash TEXT NOT NULL, outputs TEXT NOT NULL, metadata TEXT NOT NULL, "
    "completed_at TEXT NOT NULL, PRIMARY KEY (stage, unit_id))"
)


def hot_journal(path: Path) -> bool:
    journal = Path(str(path) + "-journal")
    return journal.exists() and journal.stat().st_size > 0


def recover(path: Path) -> None:
    """Roll back a crashed writer's journal; call while holding the writer lock."""
    if hot_journal(path):
        with closing(sqlite3.connect(path)) as db:
            db.execute("SELECT count(*) FROM sqlite_master").fetchone()


def read_connection(path: Path) -> sqlite3.Connection:
    """Require a checkpointed ledger, rather than ignoring a live WAL or journal.

    Immutable reads take no lock, so a journal left by a writer that is
    committing, or that crashed while committing, would expose torn pages.
    """
    wal = Path(str(path) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("Ledger has an active WAL; stop/checkpoint its writer first")
    if hot_journal(path):
        raise ValueError(
            "Ledger has a hot rollback journal: a writer is committing or crashed "
            "while committing; a writer command such as `run` or `gc` rolls it back"
        )
    return sqlite3.connect(
        path.absolute().as_uri() + "?mode=ro&immutable=1",
        uri=True,
        check_same_thread=False,
    )


class Ledger:
    def __init__(
        self,
        root: Path,
        path: Path | None,
        *,
        readonly: bool = True,
        timeout: float | None = None,
    ) -> None:
        self.root, self.path, self.readonly = root.absolute(), path, readonly
        self.lock = threading.RLock()
        if path is None or (readonly and not path.exists()):
            self.db = sqlite3.connect(":memory:", check_same_thread=False)
            self._initialize()
        elif readonly:
            self.db = read_connection(path)
        else:
            if timeout is None:
                raise ValueError(
                    "Pass the configured timeout to a writable file ledger"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(
                path,
                timeout=timeout,
                check_same_thread=False,
            )
            self.db.execute("PRAGMA synchronous=FULL")
            self._initialize()
        self.db.row_factory = sqlite3.Row

    def _initialize(self) -> None:
        self.db.execute(UNITS_SQL)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS recipes (stage TEXT NOT NULL, "
            "unit_id TEXT NOT NULL, recipe TEXT NOT NULL, "
            "PRIMARY KEY(stage, unit_id))"
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def writable(self) -> None:
        if self.readonly:
            raise ValueError("This ledger was opened read-only")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.writable()
        with self.lock, self.db:
            yield

    # Concurrent units share this connection; every statement holds the lock.
    @property
    def migrated(self) -> bool:
        with self.lock:
            return bool(
                self.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='recipes'"
                ).fetchone()
            )

    def recipes(self, stage: str | None = None) -> list[Recipe]:
        if not self.migrated:
            return []
        sql = "SELECT recipe FROM recipes"
        with self.lock:
            rows = self.db.execute(
                sql + (" WHERE stage=?" if stage else "") + " ORDER BY stage,unit_id",
                (stage,) if stage else (),
            ).fetchall()
        return [recipe_from_json(json.loads(row[0])) for row in rows]

    def recipe_stages(self) -> set[str]:
        if not self.migrated:
            return set()
        with self.lock:
            rows = self.db.execute("SELECT DISTINCT stage FROM recipes").fetchall()
        return {str(row[0]) for row in rows}

    def recipe(self, stage: str, unit_id: str) -> Recipe | None:
        with self.lock:
            row = self.db.execute(
                "SELECT recipe FROM recipes WHERE stage=? AND unit_id=?",
                (stage, unit_id),
            ).fetchone()
        return recipe_from_json(json.loads(row[0])) if row else None

    def register(self, recipe: Recipe) -> None:
        self.writable()
        self.db.execute(
            "INSERT INTO recipes VALUES(?,?,?) ON CONFLICT(stage,unit_id) "
            "DO UPDATE SET recipe=excluded.recipe",
            (recipe.stage, recipe.unit_id, encode(asdict(recipe)).decode()),
        )

    def get(self, stage: str, unit_id: str) -> Completion | None:
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM units WHERE stage=? AND unit_id=?", (stage, unit_id)
            ).fetchone()
            return self._record(row) if row is not None else None

    def records(self, stage: str | None = None) -> Iterator[Completion]:
        with self.lock:
            cursor = self.db.execute(
                "SELECT * FROM units"
                + (" WHERE stage=?" if stage else "")
                + " ORDER BY stage,unit_id",
                (stage,) if stage else (),
            )
        while True:
            with self.lock:
                rows = cursor.fetchmany(1024)
            if not rows:
                return
            for row in rows:
                yield self._record(row)

    @staticmethod
    def _record(row: sqlite3.Row) -> Completion:
        return Completion(
            row["stage"],
            row["unit_id"],
            row["inputs_hash"],
            outputs_from_json(json.loads(row["outputs"])),
            cast(Object, json.loads(row["metadata"])),
            row["completed_at"],
        )

    def store(self, record: Completion) -> None:
        self.writable()
        self.db.execute(
            "INSERT INTO units VALUES(?,?,?,?,?,?) ON CONFLICT(stage,unit_id) "
            "DO UPDATE SET inputs_hash=excluded.inputs_hash, "
            "outputs=excluded.outputs, metadata=excluded.metadata, "
            "completed_at=excluded.completed_at",
            (
                record.stage,
                record.unit_id,
                record.inputs_hash,
                encode([asdict(o) for o in record.outputs]).decode(),
                encode(record.metadata).decode(),
                record.completed_at,
            ),
        )

    def complete(
        self,
        stage: str,
        unit_id: str,
        inputs_hash: str,
        paths: Sequence[Path],
        *,
        metadata: Object | None = None,
    ) -> Completion:
        outputs, receipts = describe(self.root, paths)
        return self.record(
            stage, unit_id, inputs_hash, outputs, receipts, metadata=metadata
        )

    def record(
        self,
        stage: str,
        unit_id: str,
        inputs_hash: str,
        outputs: Sequence[Output],
        receipts: dict[str, str],
        *,
        metadata: Object | None = None,
    ) -> Completion:
        """Store described outputs; receipts are location-independent JSON digests."""
        self.writable()
        values: Object = dict(metadata or {})
        if receipts:
            values["receipts"] = dict(sorted(receipts.items()))
        record = Completion(
            stage,
            unit_id,
            inputs_hash,
            tuple(outputs),
            values,
            datetime.now(UTC).isoformat(),
        )
        with self.transaction():
            self.store(record)
        return record

    def invalidate(self, stage: str, units: Sequence[str] = ()) -> int:
        with self.transaction():
            if units:
                count = sum(
                    self.db.execute(
                        "DELETE FROM units WHERE stage=? AND unit_id=?", (stage, unit)
                    ).rowcount
                    for unit in units
                )
            else:
                count = self.db.execute(
                    "DELETE FROM units WHERE stage=?", (stage,)
                ).rowcount
        return count

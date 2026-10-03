"""Apply a verified migration with a ledger backup and recoverable JSON journal."""

import hashlib
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import cast

from pipeline.runtime.jsonio import (
    JSON,
    Object,
    atomic_output,
    read_object,
    sha256_file,
    write_json,
)
from pipeline.runtime.ledger import Ledger, read_connection
from pipeline.runtime.paths import located
from pipeline.runtime.resources import disk_free

from .adoption import Migration


def recover(root: Path, ledger_path: Path, work: Path) -> None:
    journal = work / "migration/pending.json"
    if not journal.exists():
        return
    record = read_object(journal)
    db = read_connection(ledger_path)
    try:
        has_marker = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='migration_commit'"
        ).fetchone()
        committed = (
            db.execute("SELECT digest FROM migration_commit").fetchone()[0]
            if has_marker
            else None
        )
    finally:
        db.close()
    if committed != record["digest"]:
        files = cast(list[Object], record["files"])
        # Validate the entire recovery before changing the first file.
        for item in files:
            name = str(item["path"])
            original = located(work / "migration/before", name)
            target = located(root, name)
            current = sha256_file(target) if target.exists() else None
            if current not in (item["before"], item["after"]):
                raise ValueError(f"Cannot recover manually changed metadata: {name}")
            if item["before"] is not None and sha256_file(original) != item["before"]:
                raise ValueError(f"Corrupt migration backup: {name}")
        for item in files:
            name = str(item["path"])
            original = located(work / "migration/before", name)
            target = located(root, name)
            if item["before"] is not None:
                with atomic_output(target) as temporary:
                    temporary.write_bytes(original.read_bytes())
            else:
                target.unlink(missing_ok=True)
    journal.unlink()


def apply(migration: Migration, source: Ledger, target: Path) -> None:
    """No data payload is copied or changed; only JSON metadata and the ledger."""
    ctx = migration.context
    root = ctx.root
    work = located(root, ctx.config.paths.work)
    if source.path is None or source.path.absolute() != target.absolute():
        raise ValueError("Migration must apply to the workspace's original ledger")
    if sha256_file(source.path) != migration.report["ledger_sha256"]:
        raise ValueError("Ledger changed during migration; prepare again")
    if (work / "migration/pending.json").exists():
        raise ValueError("Recover the interrupted migration before preparing another")
    before = migration.rewrites.before
    # Measure the prepared SQLite image, originals and new JSON before admitting I/O.
    db_bytes = int(ctx.ledger.db.execute("PRAGMA page_count").fetchone()[0]) * int(
        ctx.ledger.db.execute("PRAGMA page_size").fetchone()[0]
    )
    required = (
        source.path.stat().st_size
        + db_bytes
        + sum(len(value) for value in before.values())
        + sum(len(value) for value in migration.rewrites.after.values())
    )
    ctx.guard.admit(required)
    try:
        _apply(migration, source, target, work)
    finally:
        ctx.guard.release(required)


def _apply(migration: Migration, source: Ledger, target: Path, work: Path) -> None:
    root = migration.context.root
    backup = work / "ledger.pre-migration.sqlite3"
    if not backup.exists():
        with atomic_output(backup) as temporary:
            assert source.path is not None
            with source.path.open("rb") as old_stream, temporary.open("wb") as copied:
                shutil.copyfileobj(old_stream, copied)
    for name in migration.rewrites.after.keys() - migration.rewrites.before.keys():
        if located(root, name).exists():
            raise ValueError(f"New metadata path appeared during migration: {name}")
    # Confirm the observed source bytes have not changed since the dry-run logic.
    for name, original in migration.rewrites.before.items():
        if located(root, name).read_bytes() != original:
            raise ValueError(f"Metadata changed during migration: {name}")
        with atomic_output(located(work / "migration/before", name)) as temporary:
            temporary.write_bytes(original)
    marker = uuid.uuid4().hex
    db = migration.context.ledger.db
    db.execute("CREATE TABLE migration_commit (digest TEXT NOT NULL)")
    db.execute("INSERT INTO migration_commit VALUES (?)", (marker,))
    db.commit()
    journal = work / "migration/pending.json"
    files: list[JSON] = []
    for name, payload in migration.rewrites.after.items():
        before_payload = migration.rewrites.before.get(name)
        files.append(
            {
                "path": name,
                "before": hashlib.sha256(before_payload).hexdigest()
                if before_payload is not None
                else None,
                "after": hashlib.sha256(payload).hexdigest(),
            }
        )
    write_json(journal, {"digest": marker, "files": files})
    for name, payload in migration.rewrites.after.items():
        if disk_free(root) < migration.context.config.resources.disk_floor:
            # Poll with the already-reserved copy budget, never discard evidence.
            migration.context.guard.admit()
        with atomic_output(located(root, name)) as temporary:
            temporary.write_bytes(payload)
    with atomic_output(target) as temporary:
        destination = sqlite3.connect(temporary)
        try:
            db.backup(destination)
        finally:
            destination.close()
    journal.unlink()
    migration.report["mode"] = "applied"

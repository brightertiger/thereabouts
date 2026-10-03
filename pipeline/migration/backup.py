"""Preserve and verify the original ledger across separate migration steps."""

from pathlib import Path

from pipeline.runtime.jsonio import Object, sha256_file
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.paths import located
from pipeline.stages.contract import Context


def original_hash(source: Ledger) -> str | None:
    present = source.db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='migration_origin'"
    ).fetchone()
    if present:
        return str(
            source.db.execute("SELECT sha256 FROM migration_origin").fetchone()[0]
        )
    return sha256_file(source.path) if source.path else None


def verify_backup(ctx: Context, report: Object) -> Path:
    backup = located(ctx.root, ctx.config.paths.work) / "ledger.pre-migration.sqlite3"
    expected = report.get("original_ledger_sha256")
    if not isinstance(expected, str):
        raise ValueError("Migration report lacks the original ledger SHA256")
    if backup.exists() and sha256_file(backup) != expected:
        raise ValueError(
            f"Existing migration backup does not match original ledger: {backup} "
            f"(expected {expected}); preserve it and resolve the discrepancy"
        )
    if not backup.exists() and report.get("ledger_sha256") != expected:
        raise ValueError("Original ledger backup is missing after the paths step")
    return backup

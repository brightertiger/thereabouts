"""Commit a verified handover in one SQLite transaction; leave outputs untouched."""

from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.ledger import Ledger

from .handover import Handover
from .preflight import check_writable


def apply_handover(proposal: Handover, source: Ledger) -> None:
    path = source.path
    if path is None or sha256_file(path) != proposal.report["ledger_sha256"]:
        raise ValueError("Ledger changed during handover; prepare again")
    if not proposal.changes:
        return
    check_writable([path])
    with (
        Ledger(
            source.root,
            path,
            readonly=False,
            timeout=proposal.context.config.resources.ledger_timeout_seconds,
        ) as target,
        target.transaction(),
    ):
        target.db.execute(
            "CREATE TABLE IF NOT EXISTS handovers "
            "(stage TEXT PRIMARY KEY, old_identity TEXT NOT NULL, "
            "new_identity TEXT NOT NULL)"
        )
        for stage, key in proposal.changes:
            row = proposal.context.ledger.db.execute(
                "SELECT inputs_hash, metadata FROM units WHERE stage=? AND unit_id=?",
                (stage, key),
            ).fetchone()
            target.db.execute(
                "UPDATE units SET inputs_hash=?, metadata=? "
                "WHERE stage=? AND unit_id=?",
                (*row, stage, key),
            )
            recipe = proposal.context.ledger.db.execute(
                "SELECT recipe FROM recipes WHERE stage=? AND unit_id=?",
                (stage, key),
            ).fetchone()[0]
            target.db.execute(
                "UPDATE recipes SET recipe=? WHERE stage=? AND unit_id=?",
                (recipe, stage, key),
            )
        for row in proposal.context.ledger.db.execute("SELECT * FROM handovers"):
            target.db.execute("INSERT OR IGNORE INTO handovers VALUES (?,?,?)", row)
    proposal.report["mode"] = "handover applied"

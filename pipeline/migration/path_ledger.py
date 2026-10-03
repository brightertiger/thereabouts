"""Build the optional path-only ledger without adopting new stage identities."""

import json
from dataclasses import replace

from pipeline.runtime.jsonio import encode
from pipeline.runtime.ledger import Ledger

from .adoption import Migration
from .paths import legacy_relative, portable


def paths_only(migration: Migration, source: Ledger) -> Migration:
    ledger = Ledger(source.root, None, readonly=False)
    ledger.db.execute("DROP TABLE recipes")
    rewritten = 0
    with ledger.transaction():
        for row in source.db.execute("SELECT * FROM units ORDER BY stage,unit_id"):
            unit = legacy_relative(row["unit_id"], source.root)
            outputs = migration.rewrites.references(
                portable(
                    json.loads(row["outputs"]),
                    source.root,
                    migration.rewrites.aliases,
                )
            )
            metadata = migration.rewrites.references(
                portable(
                    json.loads(row["metadata"]),
                    source.root,
                    migration.rewrites.aliases,
                )
            )
            rewritten += (
                unit != row["unit_id"]
                or outputs != json.loads(row["outputs"])
                or metadata != json.loads(row["metadata"])
            )
            ledger.db.execute(
                "INSERT INTO units VALUES (?,?,?,?,?,?)",
                (
                    row["stage"],
                    unit,
                    row["inputs_hash"],
                    encode(outputs).decode(),
                    encode(metadata).decode(),
                    row["completed_at"],
                ),
            )
    report = {
        **migration.report,
        "step": "paths",
        "ledger_rows_rewritten": rewritten,
        "projected_adopted_units": migration.report["adopted_units"],
        "adopted_units": 0,
        "dropped_rows": 0,
    }
    report["projected_changes"] = report.pop("changes")
    report["projected_unit_inputs"] = report.pop("unit_inputs")
    return replace(
        migration, context=replace(migration.context, ledger=ledger), report=report
    )

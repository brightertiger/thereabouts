"""Migration command orchestration; check and dry-run never open writable data."""

import json
from pathlib import Path

from pipeline.runtime.jsonio import write_json
from pipeline.runtime.planning import counts, plan, show_counts
from pipeline.stages.contract import Context, Stage

from .adoption import simulate
from .apply import apply
from .path_ledger import paths_only


def migration_step(arguments: list[str]) -> str:
    if len(arguments) > 1 or (
        arguments and arguments[0] not in {"paths", "adopt", "check"}
    ):
        raise ValueError("migrate steps are paths, adopt, check (default: all)")
    return arguments[0] if arguments else "all"


def migrate(
    ctx: Context,
    stages: list[Stage],
    step: str,
    dry_run: bool,
    report: Path,
) -> int:
    if ctx.ledger.migrated:
        decisions = plan(ctx, stages)
        show_counts(counts(decisions))
        print("Already adopted; no migration changes.")
        write_json(
            report,
            {
                "mode": "checked",
                "stages": counts(decisions),
                "adopted_units": 0,
                "json_files_changed": 0,
                "json_files_created": 0,
                "dropped_rows": 0,
            },
        )
        return int(any(d.state != "current" for d in decisions))
    if step == "check" and not dry_run:
        raise ValueError("Ledger is not adopted; use migrate --dry-run first")
    print("Verifying migration evidence (no stage execution).", flush=True)
    migration = simulate(ctx.root, ctx.ledger, ctx.config, stages)
    path_migration = None
    try:
        if step == "paths":
            path_migration = paths_only(migration, ctx.ledger)
        selected = path_migration or migration
        if not dry_run:
            apply(selected, ctx.ledger, ctx.root / ctx.config.paths.ledger)
        write_json(report, selected.report)
        if step == "paths":
            print("Projected plan after the subsequent adopt step:")
        show_counts(counts(migration.decisions))
        print(
            json.dumps(
                {
                    key: value
                    for key, value in selected.report.items()
                    if key
                    not in {
                        "changes",
                        "json_changes",
                        "stages",
                        "identities",
                        "unit_inputs",
                        "projected_changes",
                        "projected_unit_inputs",
                    }
                },
                indent=2,
            )
        )
        print(f"Detailed migration report: {report}")
        return 0
    finally:
        migration.context.ledger.close()
        if path_migration:
            path_migration.context.ledger.close()

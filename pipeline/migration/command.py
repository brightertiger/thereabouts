"""Migration command orchestration; check and dry-run never open writable data."""

import json
from pathlib import Path

from pipeline.runtime.jsonio import write_json
from pipeline.runtime.paths import located
from pipeline.runtime.planning import counts, plan, show_counts
from pipeline.runtime.runner import exclusive
from pipeline.stages.contract import Context, Stage

from .apply import apply, recover
from .backup import verify_backup
from .handover import prepare
from .handover_apply import apply_handover
from .path_ledger import paths_only
from .preflight import (
    apply_targets,
    blocked_directories,
    check_writable,
    recovery_targets,
)
from .simulation import SIMULATION_NOTICE, simulate_handover


def migration_step(arguments: list[str]) -> str:
    if len(arguments) > 1 or (
        arguments and arguments[0] not in {"paths", "adopt", "check", "handover"}
    ):
        raise ValueError(
            "migrate steps are paths, adopt, check, handover (default: all)"
        )
    return arguments[0] if arguments else "all"


def migrate(
    ctx: Context,
    stages: list[Stage],
    step: str,
    dry_run: bool,
    report: Path,
) -> int:
    work = located(ctx.root, ctx.config.paths.work)
    target = located(ctx.root, ctx.config.paths.ledger)
    if not dry_run and step != "check" and recovery_targets(ctx.root, work):
        check_writable(recovery_targets(ctx.root, work))
        with exclusive(work / "pipeline.lock"):
            recover(ctx.root, target, work)
    if step == "handover" and ctx.ledger.migrated:
        proposal = prepare(ctx, stages)
        try:
            if not dry_run:
                check_writable([target, work / "pipeline.lock"])
                with exclusive(work / "pipeline.lock"):
                    apply_handover(proposal, ctx.ledger)
            write_json(report, proposal.report)
            show_counts(counts(proposal.decisions))
            print(json.dumps(proposal.report["identities"], indent=2))
            print(
                "Handover checks mapping and hashes only; no engine equivalence claim."
            )
            return 0
        finally:
            proposal.context.ledger.close()
    if step == "handover" and not dry_run:
        raise ValueError("Apply initial adoption before a real handover")
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
    print(SIMULATION_NOTICE, flush=True)
    migration = simulate_handover(ctx, stages)
    path_migration = None
    try:
        if step == "paths":
            path_migration = paths_only(migration, ctx.ledger)
        selected = path_migration or migration
        selected.report["writable_directories"] = [
            path.relative_to(ctx.root).as_posix()
            for path in blocked_directories(apply_targets(selected, target))
        ]
        if not dry_run:
            check_writable(apply_targets(selected, target))
            verify_backup(selected.context, selected.report)
            with exclusive(work / "pipeline.lock"):
                apply(selected, ctx.ledger, target)
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

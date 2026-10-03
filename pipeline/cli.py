"""Command-line entry for read-only planning, migration and resumable execution."""

import argparse
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from pipeline.config import Config, load
from pipeline.config.loader import CONFIG_DIR
from pipeline.migration.command import migrate, migration_step
from pipeline.migration.simulation import SIMULATION_NOTICE, simulate_handover
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.paths import located
from pipeline.runtime.planning import counts, plan, show_counts
from pipeline.runtime.resources import ResourceGuard
from pipeline.runtime.runner import exclusive, run
from pipeline.runtime.status import status
from pipeline.runtime.verification import Verifier
from pipeline.stages.contract import Context
from pipeline.stages.registry import registry


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "command", choices=("plan", "status", "run", "invalidate", "migrate")
    )
    result.add_argument(
        "arguments", nargs="*", help="stage, migration step, or key=value overrides"
    )
    result.add_argument("--root", type=Path)
    result.add_argument("--ledger", type=Path, help="read a migrated ledger copy")
    result.add_argument("--config", type=Path, default=CONFIG_DIR / "pipeline.yaml")
    result.add_argument("--profile")
    result.add_argument("--through")
    result.add_argument("--only")
    result.add_argument("--units", nargs="+")
    result.add_argument("--dry-run", action="store_true")
    result.add_argument("--report", type=Path)
    result.add_argument(
        "--details", action="store_true", help="print noncurrent unit explanations"
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_intermixed_args(argv)
    try:
        return execute(arguments)
    except (ValueError, OSError, sqlite3.Error, NotImplementedError) as error:
        print(f"pipeline: {error}")
        return 2


def execute(args: argparse.Namespace) -> int:
    overrides = [value for value in args.arguments if "=" in value]
    positional = [value for value in args.arguments if "=" not in value]
    if args.root:
        overrides.append(f"paths.root={args.root}")
    config = load(args.config, profile=args.profile, overrides=overrides)
    stages = registry(config)
    root = Path(config.paths.root).absolute()
    ledger_path = args.ledger or located(root, config.paths.ledger)
    if args.command in {"migrate", "invalidate"} and not ledger_path.exists():
        raise ValueError("No existing ledger at the configured workspace")
    if args.ledger and args.command not in {"plan", "status"}:
        raise ValueError("--ledger is only for read-only plan/status")
    if args.dry_run and args.command != "migrate":
        raise ValueError("--dry-run is only for migrate; use plan for a dry run")
    if args.command not in {"invalidate", "migrate"} and positional:
        raise ValueError(f"Unexpected arguments: {positional}")
    if args.report and args.report.resolve().is_relative_to(root.resolve()):
        raise ValueError("Read-only reports must be written outside the workspace")
    step = migration_step(positional) if args.command == "migrate" else "all"
    report = args.report or Path(".cache/pipeline/migration.json")
    if args.command == "migrate" and report.resolve().is_relative_to(root.resolve()):
        raise ValueError("Migration report must be outside the workspace")
    if (args.through or args.only) and args.command != "run":
        raise ValueError("--through and --only are run options")
    if args.through and args.only:
        raise ValueError("Use either --through or --only")
    for target in (args.through, args.only):
        if target and target not in {stage.name for stage in stages}:
            raise ValueError(f"Unknown stage: {target}")
    if args.units and args.command != "invalidate":
        raise ValueError("--units is an invalidate option")
    if args.details and args.command != "plan":
        raise ValueError("--details is a plan option")
    if args.report and args.command not in {"plan", "migrate", "status"}:
        raise ValueError("--report is a plan, status or migrate option")
    with Ledger(root, ledger_path, readonly=True) as ledger:
        ctx = context(config, root, ledger)
        if args.command == "migrate":
            return migrate(ctx, stages, step, args.dry_run, report)
        if args.command == "status":
            values = status(ledger)
            print(json.dumps(values, indent=2))
            if args.report:
                write_json(args.report, values)
            return 0
        if args.command == "invalidate":
            if len(positional) != 1 or positional[0] not in {s.name for s in stages}:
                raise ValueError("invalidate requires one registered stage")
            if not ledger.migrated:
                raise ValueError("Migrate the ledger before invalidating units")
            with exclusive(located(root, config.paths.work) / "pipeline.lock"):
                with Ledger(
                    root,
                    ledger_path,
                    readonly=False,
                    timeout=config.resources.ledger_timeout_seconds,
                ) as writable:
                    removed = writable.invalidate(positional[0], args.units or [])
                print(f"invalidated {removed} units")
            return 0
        if args.command == "run":
            if not ledger.migrated:
                raise ValueError("Migrate the legacy ledger before running")
            if not ledger.recipes():
                raise NotImplementedError(
                    "Source discovery arrives in package 2; use plan"
                )
            with Ledger(
                root,
                ledger_path,
                readonly=False,
                timeout=config.resources.ledger_timeout_seconds,
            ) as writable:
                ctx = context(config, root, writable)
                ctx.readonly = False
                print(run(ctx, stages, through=args.through, only=args.only))
            return 0
        migration = None
        if not ledger.migrated:
            print(SIMULATION_NOTICE, flush=True)
            migration = simulate_handover(ctx, stages)
            ctx = migration.context
        try:
            decisions = migration.decisions if migration else plan(ctx, stages)
            show_counts(counts(decisions))
            if args.details:
                for decision in decisions:
                    if decision.state != "current":
                        print(f"{decision.stage}/{decision.unit_id}: {decision.reason}")
            if args.report:
                write_json(
                    args.report,
                    {
                        "simulated": migration is not None,
                        "stages": counts(decisions),
                        "units": [asdict(d) for d in decisions],
                    },
                )
            return int(any(d.state != "current" for d in decisions))
        finally:
            if migration:
                migration.context.ledger.close()


def context(config: Config, root: Path, ledger: Ledger) -> Context:
    return Context(
        config,
        root,
        ledger,
        ResourceGuard(root, config.resources),
        Verifier(root),
        storage=config.storage,
    )

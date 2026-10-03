"""Parse and validate commands before opening a workspace."""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pipeline.config import Config, load
from pipeline.config.loader import CONFIG_DIR
from pipeline.migration.command import migration_step
from pipeline.runtime.paths import located
from pipeline.stages.contract import Stage
from pipeline.stages.registry import registry


@dataclass(frozen=True)
class Options:
    command: str
    config: Config
    root: Path
    ledger: Path
    stages: list[Stage]
    positional: list[str]
    step: str
    dry_run: bool
    report: Path | None
    through: str | None
    only: str | None
    units: list[str]
    details: bool


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


def parse(argv: Sequence[str] | None) -> Options:
    args = parser().parse_intermixed_args(argv)
    overrides = [value for value in args.arguments if "=" in value]
    positional = [value for value in args.arguments if "=" not in value]
    if args.root:
        overrides.append(f"paths.root={args.root}")
    config = load(args.config, profile=args.profile, overrides=overrides)
    stages = registry(config)
    root = Path(config.paths.root).absolute()
    ledger = args.ledger or located(root, config.paths.ledger)
    if args.command in {"migrate", "invalidate"} and not ledger.exists():
        raise ValueError("No existing ledger at the configured workspace")
    if args.ledger and args.command not in {"plan", "status"}:
        raise ValueError("--ledger is only for read-only plan/status")
    if args.dry_run and args.command != "migrate":
        raise ValueError("--dry-run is only for migrate; use plan for a dry run")
    if args.command not in {"invalidate", "migrate"} and positional:
        raise ValueError(f"Unexpected arguments: {positional}")
    if (args.through or args.only) and args.command != "run":
        raise ValueError("--through and --only are run options")
    if args.through and args.only:
        raise ValueError("Use either --through or --only")
    names = {stage.name for stage in stages}
    for target in (args.through, args.only):
        if target and target not in names:
            raise ValueError(f"Unknown stage: {target}")
    if args.command == "invalidate" and (
        len(positional) != 1 or positional[0] not in names
    ):
        raise ValueError("invalidate requires one registered stage")
    if args.units and args.command != "invalidate":
        raise ValueError("--units is an invalidate option")
    if args.details and args.command != "plan":
        raise ValueError("--details is a plan option")
    if args.report and args.command not in {"plan", "migrate", "status"}:
        raise ValueError("--report is a plan, status or migrate option")
    step = migration_step(positional) if args.command == "migrate" else "all"
    report = args.report
    if args.command == "migrate" and report is None:
        report = Path(".cache/pipeline/migration.json")
    if report and report.resolve().is_relative_to(root.resolve()):
        raise ValueError("Read-only reports must be written outside the workspace")
    return Options(
        args.command,
        config,
        root,
        ledger,
        stages,
        positional,
        step,
        args.dry_run,
        report,
        args.through,
        args.only,
        args.units or [],
        args.details,
    )

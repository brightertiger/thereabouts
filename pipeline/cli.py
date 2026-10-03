"""Command-line entry for read-only planning, migration and resumable execution."""

import sqlite3
from collections.abc import Sequence

from pipeline.arguments import parse
from pipeline.commands import execute_run, inspect_plan, inspect_status, invalidate
from pipeline.migration.command import migrate
from pipeline.runtime.context import context
from pipeline.runtime.ledger import Ledger


def main(argv: Sequence[str] | None = None) -> int:
    try:
        options = parse(argv)
        with Ledger(options.root, options.ledger, readonly=True) as ledger:
            ctx = context(options.config, options.root, ledger)
            if options.command == "migrate":
                if options.report is None:
                    raise ValueError("Migration requires a report path")
                return migrate(
                    ctx, options.stages, options.step, options.dry_run, options.report
                )
            handlers = {
                "plan": inspect_plan,
                "status": inspect_status,
                "invalidate": invalidate,
                "run": execute_run,
            }
            return handlers[options.command](ctx, options)
    except (ValueError, OSError, sqlite3.Error, NotImplementedError) as error:
        print(f"pipeline: {error}")
        return 2

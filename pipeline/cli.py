"""Command-line entry for read-only planning, migration and resumable execution."""

import sqlite3
import sys
from collections.abc import Sequence

from pipeline.arguments import parse
from pipeline.commands import (
    collect_garbage,
    execute_run,
    inspect_plan,
    inspect_status,
    invalidate,
)
from pipeline.content.command import main as digest_main
from pipeline.migration.command import migrate
from pipeline.pins.cli import main as pins_main
from pipeline.release_command import main as release_main
from pipeline.runtime.context import context
from pipeline.runtime.ledger import Ledger, hot_journal, recover
from pipeline.runtime.paths import located
from pipeline.runtime.runner import exclusive
from pipeline.tools.dictionary import main as dictionary_main

WRITERS = {"run", "invalidate", "gc", "migrate"}


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = list(sys.argv[1:] if argv is None else argv)
        if arguments[:1] == ["release"]:
            return release_main(arguments[1:])
        if arguments[:1] == ["dictionary"]:
            return dictionary_main(arguments[1:])
        if arguments[:1] == ["digest"]:
            return digest_main(arguments[1:])
        if arguments[:1] == ["pins"]:
            return pins_main(arguments[1:])
        options = parse(arguments)
        if options.command in WRITERS and hot_journal(options.ledger):
            work = located(options.root, options.config.paths.work)
            with exclusive(work / "pipeline.lock"):
                recover(options.ledger)
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
                "gc": collect_garbage,
            }
            return handlers[options.command](ctx, options)
    except (ValueError, OSError, sqlite3.Error, NotImplementedError) as error:
        print(f"pipeline: {error}")
        return 2

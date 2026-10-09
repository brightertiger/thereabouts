"""Command handlers joining runtime operations with migration inspection."""

import json
from dataclasses import asdict

from pipeline.arguments import Options
from pipeline.migration.paths import legacy_relative
from pipeline.migration.simulation import SIMULATION_NOTICE, simulate_handover
from pipeline.runtime.context import context
from pipeline.runtime.gc import garbage, remove, size
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.paths import located
from pipeline.runtime.planning import counts, plan, show_counts
from pipeline.runtime.runner import exclusive, run
from pipeline.runtime.status import status
from pipeline.stages.contract import Context


def inspect_plan(ctx: Context, options: Options) -> int:
    migration = None
    if not ctx.ledger.migrated:
        print(SIMULATION_NOTICE, flush=True)
        migration = simulate_handover(ctx, options.stages)
        ctx = migration.context
    try:
        decisions = migration.decisions if migration else plan(ctx, options.stages)
        show_counts(counts(decisions))
        if options.details:
            for decision in decisions:
                if decision.state != "current":
                    print(f"{decision.stage}/{decision.unit_id}: {decision.reason}")
        if options.report:
            write_json(
                options.report,
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


def inspect_status(ctx: Context, options: Options) -> int:
    values = status(ctx.ledger, lambda name: legacy_relative(name, ctx.root))
    print(json.dumps(values, indent=2))
    if options.report:
        write_json(options.report, values)
    return 0


def invalidate(ctx: Context, options: Options) -> int:
    if not ctx.ledger.migrated:
        raise ValueError("Migrate the ledger before invalidating units")
    with exclusive(located(ctx.root, ctx.config.paths.work) / "pipeline.lock"):
        with Ledger(
            ctx.root,
            options.ledger,
            readonly=False,
            timeout=ctx.config.resources.ledger_timeout_seconds,
        ) as writable:
            removed = writable.invalidate(options.positional[0], options.units)
        print(f"invalidated {removed} units")
    return 0


def collect_garbage(ctx: Context, options: Options) -> int:
    if not ctx.ledger.migrated:
        raise ValueError("Migrate the ledger before collecting garbage")
    with exclusive(located(ctx.root, ctx.config.paths.work) / "pipeline.lock"):
        # Read the ledger again under the lock, so no writer commits meanwhile.
        with Ledger(ctx.root, options.ledger, readonly=True) as ledger:
            paths = garbage(ctx.root, ctx.config, ledger)
        verb = "would remove" if options.dry_run else "removing"
        total = 0
        for path in paths:
            total += (count := size(path))
            print(f"{verb} {path.relative_to(ctx.root)} ({count} bytes)")
        if not options.dry_run:
            remove(paths)
        print(f"{verb} {len(paths)} paths, {total} bytes")
    return 0


def execute_run(ctx: Context, options: Options) -> int:
    if not ctx.ledger.migrated:
        raise ValueError("Migrate the legacy ledger before running")
    with Ledger(
        ctx.root,
        options.ledger,
        readonly=False,
        timeout=ctx.config.resources.ledger_timeout_seconds,
    ) as writable:
        writable_context = context(ctx.config, ctx.root, writable)
        writable_context.readonly = False
        print(
            run(
                writable_context,
                options.stages,
                through=options.through,
                only=options.only,
            )
        )
    return 0

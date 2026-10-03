"""Simulate legacy adoption separately from independent ported-stage discovery."""

from collections.abc import Sequence
from dataclasses import replace

from pipeline.config import load
from pipeline.config.loader import CONFIG_DIR
from pipeline.stages.contract import Context, Stage
from pipeline.stages.retained import RetainedStage

from .adoption import Migration, simulate
from .handover import prepare

SIMULATION_NOTICE = (
    "SIMULATED ADOPTION/HANDOVER: on-disk ledger unchanged. "
    "Zero stale is by construction; this checks mapping and hashes only, "
    "not engine equivalence."
)


def simulate_handover(ctx: Context, stages: Sequence[Stage]) -> Migration:
    baseline = load(CONFIG_DIR / "adoption.yaml")
    retained = [RetainedStage(settings) for settings in baseline.stages]
    migration = simulate(ctx.root, ctx.ledger, ctx.config, retained)
    if all(isinstance(stage, RetainedStage) for stage in stages):
        return migration
    try:
        proposal = prepare(migration.context, stages)
        return replace(
            migration,
            context=proposal.context,
            report={**migration.report, "handover": proposal.report},
            decisions=proposal.decisions,
        )
    finally:
        migration.context.ledger.close()

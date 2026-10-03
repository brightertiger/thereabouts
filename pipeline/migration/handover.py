"""Verify an adopted stage's independent discovery before changing its identity."""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from pipeline.runtime.jsonio import JSON, Object, sha256_file
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import Decision, counts, plan
from pipeline.stages.contract import Context, Stage, make_unit
from pipeline.stages.registry import ordered
from pipeline.stages.retained import RetainedStage


@dataclass
class Handover:
    context: Context
    changes: list[tuple[str, str]]
    report: Object
    decisions: list[Decision]


def prepare(ctx: Context, stages: Sequence[Stage]) -> Handover:
    if not ctx.ledger.migrated:
        raise ValueError("Handover requires an already-adopted ledger")
    ledger = Ledger(ctx.root, None, readonly=False)
    ctx.ledger.db.backup(ledger.db)
    proposed = replace(ctx, ledger=ledger)
    complete = False
    try:
        result = _prepare(ctx, proposed, stages)
        complete = True
        return result
    finally:
        if not complete:
            ledger.close()


def _prepare(ctx: Context, proposed: Context, stages: Sequence[Stage]) -> Handover:
    ledger = proposed.ledger
    ledger.db.execute(
        "CREATE TABLE IF NOT EXISTS handovers "
        "(stage TEXT PRIMARY KEY, old_identity TEXT NOT NULL, "
        "new_identity TEXT NOT NULL)"
    )
    changes: list[tuple[str, str]] = []
    reports: list[JSON] = []
    for stage in ordered(stages):
        if isinstance(stage, RetainedStage):
            continue
        previous = {recipe.key: recipe for recipe in ledger.recipes(stage.name)}
        discovered = stage.units(proposed)
        keys = {unit.key for unit in discovered}
        if len(keys) != len(discovered) or keys != previous.keys():
            raise ValueError(
                f"Handover key mismatch for {stage.name}: "
                f"missing={sorted(previous.keys() - keys)[:10]}, "
                f"new={sorted(keys - previous.keys())[:10]}"
            )
        recorded = {record.key: record for record in ledger.records(stage.name)}
        if recorded.keys() != keys:
            raise ValueError(f"Handover requires every completion for {stage.name}")
        already = ledger.db.execute(
            "SELECT 1 FROM handovers WHERE stage=?", (stage.name,)
        ).fetchone()
        identity = stage.identity(proposed)
        old = {str(record.metadata.get("identity")) for record in recorded.values()}
        changed = 0
        # Stage units may have dependencies in earlier stages; the whole graph is
        # checked by plan below, after identity/parameter changes are prepared.
        for initial in discovered:
            record = recorded[initial.key]
            if not record.metadata.get("adopted"):
                raise ValueError(f"Not an adopted completion: {initial.key}")
            if problem := ctx.verifier.completion_problem(record):
                raise ValueError(f"Cannot hand over {initial.key}: {problem}")
            if initial.recipe.dependencies != previous[initial.key].dependencies:
                raise ValueError(f"Handover cannot change dependencies: {initial.key}")
            unit = make_unit(proposed, initial.recipe, identity)
            if unit.dependency_hash != record.metadata.get("dependency_hash"):
                raise ValueError(f"Handover cannot change upstream bytes: {unit.key}")
            needs_change = (
                record.metadata.get("identity") != identity
                or record.inputs_hash != unit.inputs_hash
                or previous[unit.key].parameters != unit.recipe.parameters
            )
            if not needs_change:
                continue
            if already:
                raise ValueError(
                    f"Stage {stage.name} already handed over; rebuild changed units"
                )
            ledger.register(unit.recipe)
            ledger.store(
                replace(
                    record,
                    inputs_hash=unit.inputs_hash,
                    metadata={**record.metadata, "identity": identity},
                )
            )
            changes.append(unit.key)
            changed += 1
        if changed:
            ledger.db.execute(
                "INSERT INTO handovers VALUES (?,?,?)",
                (stage.name, ",".join(sorted(old)), identity),
            )
        reports.append(
            {
                "stage": stage.name,
                "units": len(keys),
                "changed": changed,
                "old_identity": [value for value in sorted(old)],
                "new_identity": identity,
            }
        )
    ledger.db.commit()
    decisions = plan(proposed, stages)
    if any(decision.state != "current" for decision in decisions):
        raise ValueError("Handover would leave stale or new units; inspect plan")
    return Handover(
        proposed,
        changes,
        {
            "mode": "handover simulation",
            "ledger_sha256": sha256_file(ctx.ledger.path) if ctx.ledger.path else None,
            "identities": reports,
            "changed_units": len(changes),
            "stages": {name: dict(value) for name, value in counts(decisions).items()},
            "scope": "mapping and hashes only; no engine equivalence claim",
        },
        decisions,
    )

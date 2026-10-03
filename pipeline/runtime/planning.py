"""Explain every work decision, including declared inputs that are unavailable."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pipeline.stages.contract import Context, Stage, Unit
from pipeline.stages.registry import ordered

State = Literal["current", "stale", "new"]


@dataclass(frozen=True)
class Decision:
    stage: str
    unit_id: str
    state: State
    reason: str
    outputs_absent: int = 0


def decide(ctx: Context, unit: Unit) -> Decision:
    stage, key = unit.key
    record = ctx.ledger.get(stage, key)
    if record is None:
        return Decision(stage, key, "new", "no completion record")
    if record.metadata.get("identity") != unit.identity:
        return Decision(stage, key, "stale", "identity changed")
    if record.inputs_hash != unit.inputs_hash:
        reason = (
            "upstream output changed"
            if record.metadata.get("dependency_hash") != unit.dependency_hash
            else "unit parameters changed"
        )
        return Decision(stage, key, "stale", reason)
    if problem := ctx.verifier.completion_problem(record):
        return Decision(stage, key, "stale", problem)
    absent = record.metadata.get("absent_paths", [])
    count = len(absent) if isinstance(absent, list) else 0
    return Decision(
        stage,
        key,
        "current",
        "recorded outputs absent"
        if count
        else "identity, inputs and output hashes match",
        count,
    )


def order_units(units: Sequence[Unit]) -> list[Unit]:
    by_key = {unit.key: unit for unit in units}
    if len(by_key) != len(units):
        raise ValueError("Duplicate unit identities")
    done: set[tuple[str, str]] = set()
    visiting: set[tuple[str, str]] = set()
    result = []

    def visit(unit: Unit) -> None:
        if unit.key in visiting:
            raise ValueError(f"Unit dependency cycle: {unit.key}")
        if unit.key in done:
            return
        visiting.add(unit.key)
        for dep in unit.recipe.dependencies:
            if dep.key not in by_key:
                raise ValueError(f"Undeclared dependency: {dep.key}")
            visit(by_key[dep.key])
        visiting.remove(unit.key)
        done.add(unit.key)
        result.append(unit)

    for unit in units:
        visit(unit)
    return result


def plan(ctx: Context, stages: Sequence[Stage]) -> list[Decision]:
    registered = {stage.name for stage in stages}
    unknown = {r.stage for r in ctx.ledger.recipes()} - registered
    if unknown:
        raise ValueError(f"Ledger has unregistered stages: {sorted(unknown)}")
    units = order_units(
        [unit for stage in ordered(stages) for unit in stage.units(ctx)]
    )
    decisions: dict[tuple[str, str], Decision] = {}
    for unit in units:
        decision = decide(ctx, unit)
        for dependency in unit.recipe.dependencies:
            if decisions[dependency.key].state != "current":
                decision = Decision(
                    *unit.key,
                    "stale" if decision.state == "current" else decision.state,
                    f"upstream unit changed: {dependency.stage}/{dependency.unit_id}",
                )
                break
        decisions[unit.key] = decision
    return list(decisions.values())


def counts(decisions: Sequence[Decision]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for decision in decisions:
        stage = result.setdefault(
            decision.stage,
            {
                "current": 0,
                "stale": 0,
                "new": 0,
                "outputs_absent": 0,
            },
        )
        stage[decision.state] += 1
        stage["outputs_absent"] += bool(decision.outputs_absent)
    return result


def show_counts(values: dict[str, dict[str, int]]) -> None:
    print("stage               current   stale     new   absent")
    for name, value in values.items():
        print(
            f"{name:20} {value['current']:7} {value['stale']:7} "
            f"{value['new']:7} {value['outputs_absent']:8}"
        )

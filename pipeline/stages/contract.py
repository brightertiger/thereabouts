"""The small stage surface; discovery and execution are separate operations."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pipeline.config import Config
from pipeline.runtime.jsonio import digest
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Dependency, Recipe, output_json
from pipeline.runtime.resources import ResourceGuard
from pipeline.runtime.verification import Verifier


@dataclass
class Context:
    config: Config
    root: Path
    ledger: Ledger
    guard: ResourceGuard
    verifier: Verifier
    readonly: bool = True
    storage: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Unit:
    recipe: Recipe
    identity: str
    inputs_hash: str
    dependency_hash: str
    required_bytes: int = 0
    accounts_disk: bool = False
    refresh_discovery: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return self.recipe.key


class Stage(Protocol):
    name: str
    needs: tuple[str, ...]

    def identity(self, ctx: Context) -> str: ...
    def units(self, ctx: Context) -> list[Unit]: ...
    def run(self, ctx: Context, unit: Unit) -> list[Path]: ...
    def finish(self, ctx: Context) -> None:
        """Publish idempotently, including after interrupted finalization."""
        ...


def dependency_value(ctx: Context, dependency: Dependency) -> object:
    if dependency.control:
        return {"stage": dependency.stage, "unit": dependency.unit_id, "control": True}
    record = ctx.ledger.get(*dependency.key)
    if record is None:
        return {"stage": dependency.stage, "unit": dependency.unit_id, "missing": True}
    outputs = [
        output_json(output)
        for output in record.outputs
        if not dependency.paths or output.path in dependency.paths
    ]
    if dependency.paths and len(outputs) != len(dependency.paths):
        raise ValueError(f"Dependency refers to unrecorded outputs: {dependency.key}")
    return {"stage": dependency.stage, "unit": dependency.unit_id, "outputs": outputs}


def make_unit(ctx: Context, recipe: Recipe, identity: str) -> Unit:
    dependencies = digest([dependency_value(ctx, dep) for dep in recipe.dependencies])
    return Unit(
        recipe,
        identity,
        digest(
            {
                "identity": identity,
                "parameters": recipe.parameters,
                "upstream": dependencies,
            }
        ),
        dependencies,
    )

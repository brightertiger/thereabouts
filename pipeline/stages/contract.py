"""The small stage surface; discovery and execution are separate operations."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

from pipeline.config import Config
from pipeline.runtime.jsonio import digest
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.outputs import role, selected
from pipeline.runtime.records import Dependency, Recipe
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
    receipts = cast(dict[str, str], record.metadata.get("receipts", {}))
    # Roles and receipt digests omit inputs-hash directories, so an upstream
    # re-run that only moved identical bytes leaves this value unchanged.
    outputs = sorted(
        (
            role(output.path),
            output.size,
            receipts.get(output.path, output.sha256),
        )
        for output in selected(record.outputs, dependency.paths)
    )
    return {
        "stage": dependency.stage,
        "unit": dependency.unit_id,
        "outputs": [
            {"role": name, "size": size, "sha256": sha} for name, size, sha in outputs
        ],
    }


def make_unit(ctx: Context, recipe: Recipe, identity: str) -> Unit:
    dependencies = digest([dependency_value(ctx, dep) for dep in recipe.dependencies])
    return Unit(
        recipe,
        identity,
        # The unit id keeps output directories named by inputs hash unshared.
        digest(
            {
                "unit": recipe.unit_id,
                "identity": identity,
                "parameters": recipe.parameters,
                "upstream": dependencies,
            }
        ),
        dependencies,
    )

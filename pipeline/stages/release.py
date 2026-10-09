"""Shared identity and discovery mechanics for immutable release stages."""

from dataclasses import replace
from pathlib import Path

from pipeline.config.schema import StageSettings
from pipeline.runtime.fingerprints import stage_identity
from pipeline.runtime.jsonio import Object, digest
from pipeline.runtime.records import Dependency, Recipe
from thereabouts.format import CELL_FORMAT_VERSION

from .contract import Context, Unit, make_unit

REVISIONS = ("CORE_REVISION", "WRITER_REVISION")


def writer_revisions() -> dict[str, str]:
    """The Rust writer's encoding revisions change pack bytes without a release."""
    from thereabouts import _core

    # Read the module namespace: the client's type stub predates these constants.
    values = vars(_core)
    revisions = {name: str(values[name]) for name in REVISIONS if name in values}
    if "WRITER_REVISION" not in revisions:
        raise ValueError("thereabouts._core lacks WRITER_REVISION; rebuild it")
    return revisions


class ReleaseStage:
    def __init__(self, settings: StageSettings) -> None:
        self.settings = settings
        self.name = settings.name
        self.needs = tuple(settings.needs)

    def identity(self, ctx: Context) -> str:
        value = stage_identity(
            self.settings,
            ctx.config,
            cell_format=CELL_FORMAT_VERSION,
            read=ctx.watch.read,
        )
        if "thereabouts" not in self.settings.native:
            return value
        # The writer is Rust, outside every hashed closure; its revisions stand in.
        return digest({"stage": value, "writer": writer_revisions()})

    def unit(
        self,
        ctx: Context,
        key: str,
        parameters: Object,
        dependencies: tuple[Dependency, ...],
    ) -> Unit:
        recipe = Recipe(self.name, key, parameters, dependencies)
        return replace(make_unit(ctx, recipe, self.identity(ctx)), accounts_disk=True)

    def units(self, ctx: Context) -> list[Unit]:
        raise NotImplementedError

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        raise NotImplementedError

    def finish(self, ctx: Context) -> None:
        return None

    def check_writable(self, ctx: Context) -> None:
        if ctx.readonly:
            raise ValueError("Cannot execute a release stage with a read-only context")

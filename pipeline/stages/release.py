"""Shared identity and discovery mechanics for immutable release stages."""

from dataclasses import replace
from pathlib import Path

from pipeline.config.schema import StageSettings
from pipeline.runtime.fingerprints import stage_identity
from pipeline.runtime.jsonio import Object
from pipeline.runtime.records import Dependency, Recipe

from .contract import Context, Unit, make_unit


class ReleaseStage:
    def __init__(self, settings: StageSettings) -> None:
        self.settings = settings
        self.name = settings.name
        self.needs = tuple(settings.needs)

    def identity(self, ctx: Context) -> str:
        return stage_identity(self.settings, ctx.config)

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

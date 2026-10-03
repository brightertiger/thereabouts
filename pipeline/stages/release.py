"""Shared identity and discovery mechanics for immutable release stages."""

from dataclasses import asdict, replace
from pathlib import Path

from pipeline.config.schema import StageSettings
from pipeline.runtime.fingerprints import REPOSITORY, identity, native_versions
from pipeline.runtime.jsonio import Object
from pipeline.runtime.records import Dependency, Recipe
from thereabouts.format import CELL_FORMAT_VERSION

from .contract import Context, Unit, make_unit


class ReleaseStage:
    def __init__(self, settings: StageSettings) -> None:
        self.settings = settings
        self.name = settings.name
        self.needs = tuple(settings.needs)

    def identity(self, ctx: Context) -> str:
        tree = asdict(ctx.config)
        return identity(
            [REPOSITORY / path for path in self.settings.packages],
            config={
                "stage": asdict(self.settings),
                **{name: tree[name] for name in self.settings.config},
            },
            pins={},
            native=native_versions(self.settings.native, REPOSITORY / "uv.lock"),
            cell_format=CELL_FORMAT_VERSION if self.settings.cell_format else None,
        )

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

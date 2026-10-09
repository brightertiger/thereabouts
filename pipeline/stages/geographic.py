"""Geographic stage identities and units; execution stays in focused stage modules."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from pipeline.config.schema import StageSettings
from pipeline.runtime.fingerprints import stage_identity

from .contract import Context, Unit, make_unit
from .engine_data import Geography
from .engine_discovery import Discovery
from .parameters import Configure


class GeographicStage:
    def __init__(
        self,
        settings: StageSettings,
        discovery: Discovery,
        execute: Callable[[Context, Unit], list[Path]],
        finalize: Callable[[Context], None],
        parameters: Callable[[Context, Geography], Configure],
    ) -> None:
        self.settings, self.discovery = settings, discovery
        self.name, self.needs = settings.name, tuple(settings.needs)
        self.execute, self.finalize = execute, finalize
        self.parameters = parameters

    def identity(self, ctx: Context) -> str:
        return stage_identity(self.settings, ctx.config)

    def units(self, ctx: Context) -> list[Unit]:
        self.discovery.load(ctx)
        configure = self.parameters(ctx, self.discovery.geography)
        current_identity = self.identity(ctx)
        result = []
        for recipe in self.discovery.recipes.get(self.name, []):
            options = configure(recipe)
            unit = make_unit(
                ctx, replace(recipe, parameters=options.parameters), current_identity
            )
            result.append(
                replace(
                    unit,
                    required_bytes=options.required_bytes,
                    refresh_discovery=options.refresh_discovery,
                )
            )
        return result

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        if ctx.readonly:
            raise ValueError(
                "Cannot execute a geographic stage with a read-only context"
            )
        return self.execute(ctx, unit)

    def finish(self, ctx: Context) -> None:
        self.finalize(ctx)

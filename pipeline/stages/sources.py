"""Discover source units from YAML and the lock, independently of ledger recipes."""

import importlib
from dataclasses import asdict, replace
from pathlib import Path
from typing import cast

from pipeline.config.schema import StageSettings
from pipeline.pins.models import SourcePin
from pipeline.runtime.fingerprints import REPOSITORY, identity, native_versions
from pipeline.runtime.jsonio import Object
from pipeline.runtime.records import Dependency, Recipe
from pipeline.sources.contract import Source, SourceContext
from pipeline.sources.download import download

from .contract import Context, Unit, make_unit


class SourceStage:
    def __init__(self, settings: StageSettings, pins: dict[str, SourcePin]) -> None:
        self.settings, self.pins = settings, pins
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
            pins={
                name: asdict(self.pins[name])
                for name, source in ctx.config.sources.items()
                if source.enabled
            },
            native=native_versions(self.settings.native, REPOSITORY / "uv.lock"),
        )

    def units(self, ctx: Context) -> list[Unit]:
        current_identity = self.identity(ctx)
        units = []
        for name, settings in sorted(ctx.config.sources.items()):
            if not settings.enabled:
                continue
            pin = self.pins[name]
            if not pin.available:
                raise ValueError(f"Enabled source has no reviewed pin: {name}")
            recipe = Recipe(
                self.name,
                name,
                cast(Object, {"source": asdict(settings), "release": pin.release}),
                (Dependency("download", name),) if self.name == "normalize" else (),
            )
            unit = make_unit(ctx, recipe, current_identity)
            # Downloads reserve the pinned bytes. Normalizers admit bounded
            # publications and cache allocations as they stream through the input.
            required = (
                sum(item.size for item in pin.files) if self.name == "download" else 0
            )
            units.append(
                replace(
                    unit,
                    required_bytes=required,
                    accounts_disk=self.name == "normalize",
                )
            )
        return units

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        if ctx.readonly:
            raise ValueError("Cannot execute a source with a read-only context")
        name = unit.recipe.unit_id
        source = SourceContext(ctx, ctx.config.sources[name], self.pins[name], unit)
        if self.name == "download":
            return download(source)
        adapter = cast(Source, importlib.import_module(source.settings.adapter))
        return adapter.normalize(source)

    def finish(self, ctx: Context) -> None:
        # Each source publishes its own manifest before its unit is committed.
        return None

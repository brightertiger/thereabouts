"""Discover source units from YAML and the lock, independently of ledger recipes."""

import importlib
from dataclasses import asdict, replace
from pathlib import Path
from typing import cast

from pipeline.config.schema import StageSettings
from pipeline.config.sources import SourceSettings, normalize_settings
from pipeline.pins.models import SourcePin
from pipeline.runtime.fingerprints import REPOSITORY, adapter_hashes, stage_identity
from pipeline.runtime.jsonio import Object, digest
from pipeline.runtime.records import Dependency, Recipe
from pipeline.sources.contract import Source, SourceContext
from pipeline.sources.download import download
from pipeline.sources.policy import policy_hashes

from .contract import Context, Unit, make_unit


def adapter_digest(module: str) -> str:
    return digest(adapter_hashes(module, REPOSITORY))


def adapter_context(
    ctx: Context, settings: SourceSettings, pin: SourcePin, unit: Unit
) -> SourceContext:
    """Only a writable run hands an adapter its narrow view of the runtime."""
    if ctx.readonly:
        raise ValueError("Cannot execute a source with a read-only context")
    return SourceContext(
        settings=settings,
        pin=pin,
        inputs_hash=unit.inputs_hash,
        root=ctx.root,
        paths=ctx.config.paths,
        grid=ctx.config.h3,
        guard=ctx.guard,
        storage=ctx.storage,
        log=ctx.log,
    )


class SourceStage:
    def __init__(self, settings: StageSettings, pins: dict[str, SourcePin]) -> None:
        self.settings, self.pins = settings, pins
        self.name = settings.name
        self.needs = tuple(settings.needs)

    def identity(self, ctx: Context) -> str:
        return stage_identity(self.settings, ctx.config, repository=REPOSITORY)

    def units(self, ctx: Context) -> list[Unit]:
        current_identity = self.identity(ctx)
        units = []
        for name, settings in sorted(ctx.config.sources.items()):
            if not settings.enabled:
                continue
            pin = self.pins[name]
            if not pin.available:
                raise ValueError(f"Enabled source has no reviewed pin: {name}")
            # Downloads fetch exactly the pinned bytes; transfer limits and upstream
            # URLs change how, not what. Normalizers hash what they read.
            parameters: Object = {"pin": cast(Object, asdict(pin))}
            if self.name == "normalize":
                parameters |= {
                    "adapter": adapter_digest(settings.adapter),
                    "policies": cast(Object, policy_hashes(settings)),
                    "settings": cast(Object, normalize_settings(settings)),
                }
            recipe = Recipe(
                self.name,
                name,
                parameters,
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
        name = unit.recipe.unit_id
        source = adapter_context(ctx, ctx.config.sources[name], self.pins[name], unit)
        if self.name == "download":
            return download(source)
        adapter = cast(Source, importlib.import_module(source.settings.adapter))
        return adapter.normalize(source)

    def finish(self, ctx: Context) -> None:
        # Each source publishes its own manifest before its unit is committed.
        return None

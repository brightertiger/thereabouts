"""Discover source units from YAML and the lock, independently of ledger recipes."""

import importlib
from dataclasses import asdict, replace
from pathlib import Path
from typing import cast

from pipeline.config.schema import StageSettings
from pipeline.pins.models import SourcePin
from pipeline.runtime.code import code_hashes
from pipeline.runtime.fingerprints import REPOSITORY, identity, native_versions
from pipeline.runtime.jsonio import Object, digest
from pipeline.runtime.records import Dependency, Recipe
from pipeline.sources.contract import Source, SourceContext
from pipeline.sources.download import download
from pipeline.sources.policy import policy_hashes

from .contract import Context, Unit, make_unit


def adapter_digest(module: str) -> str:
    stem = REPOSITORY.joinpath(*module.split("."))
    path = stem if stem.is_dir() else stem.with_suffix(".py")
    return digest(code_hashes([path], REPOSITORY))


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
            pins={},
            repository=REPOSITORY,
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
                cast(
                    Object,
                    {
                        "source": asdict(settings),
                        "pin": asdict(pin),
                        "adapter": adapter_digest(settings.adapter),
                        "policies": policy_hashes(settings),
                    },
                ),
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

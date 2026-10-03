"""Read adopted recipes while their source/engine implementations are being moved.

This stage can inspect verified existing results. It cannot rebuild them. The
runtime runner is exercised with executable synthetic stages until packages 2-3
replace these declarations with source and engine implementations.
"""

from dataclasses import asdict
from pathlib import Path

from pipeline.config.schema import StageSettings
from pipeline.runtime.fingerprints import REPOSITORY, identity, native_versions
from thereabouts.format import CELL_FORMAT_VERSION

from .contract import Context, Unit, make_unit


class RetainedStage:
    def __init__(self, settings: StageSettings) -> None:
        self.settings = settings
        self.name = settings.name
        self.needs = tuple(settings.needs)

    def identity(self, ctx: Context) -> str:
        tree = asdict(ctx.config)
        return identity(
            [REPOSITORY / p for p in self.settings.packages],
            config={
                "stage": asdict(self.settings),
                **{key: tree[key] for key in self.settings.config},
            },
            pins={},
            native=native_versions(self.settings.native, REPOSITORY / "uv.lock"),
            cell_format=CELL_FORMAT_VERSION if self.settings.cell_format else None,
        )

    def units(self, ctx: Context) -> list[Unit]:
        current_identity = self.identity(ctx)
        return [
            make_unit(ctx, recipe, current_identity)
            for recipe in ctx.ledger.recipes(self.name)
        ]

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        raise NotImplementedError(
            f"{self.name} execution is not ported yet; runtime-core only. "
            "Do not run the legacy builder against an adopted workspace."
        )

    def finish(self, ctx: Context) -> None:
        # A current retained manifest is already published. Stale units cannot run.
        return None

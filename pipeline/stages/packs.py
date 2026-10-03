"""Delegate each requested pack family to the client package's writer."""

from pathlib import Path

from pipeline.release import client
from pipeline.runtime.paths import located
from pipeline.runtime.records import Dependency

from .contract import Context, Unit
from .release import ReleaseStage


class PacksStage(ReleaseStage):
    def units(self, ctx: Context) -> list[Unit]:
        if not ctx.config.release.enabled:
            return []
        version = ctx.config.release.version
        return [
            self.unit(
                ctx,
                f"{version}/{family}",
                {"family": family, "version": version},
                (Dependency("dataset", version),),
            )
            for family in ctx.config.release.packs.families
        ]

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        self.check_writable(ctx)
        version, family = unit.recipe.unit_id.split("/")
        dataset = located(ctx.root, ctx.config.paths.dataset) / version
        output = located(ctx.root, ctx.config.paths.packs) / version / family
        return client.write(dataset, family, output, version, client.binding())

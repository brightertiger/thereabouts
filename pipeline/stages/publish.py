"""Publish the completed dataset and requested client packs, then retain a receipt."""

from dataclasses import asdict
from pathlib import Path
from typing import cast

from pipeline.release.publish import inventory, publish
from pipeline.runtime.jsonio import Object, write_json
from pipeline.runtime.paths import located
from pipeline.runtime.records import Dependency

from .contract import Context, Unit
from .release import ReleaseStage


class PublishStage(ReleaseStage):
    def units(self, ctx: Context) -> list[Unit]:
        if not ctx.config.release.enabled:
            return []
        version = ctx.config.release.version
        dependencies = (
            Dependency("dataset", version),
            *(
                (Dependency("packs", f"{version}/index"),)
                if ctx.config.release.packs.families
                else ()
            ),
        )
        return [
            self.unit(
                ctx,
                version,
                {
                    "version": version,
                    "destination": ctx.storage.get("s3_release", ""),
                    "options": cast(Object, asdict(ctx.config.release.publish)),
                },
                dependencies,
            )
        ]

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        self.check_writable(ctx)
        version = ctx.config.release.version
        dataset = located(ctx.root, ctx.config.paths.dataset) / version
        packs = {
            family: located(ctx.root, ctx.config.paths.packs) / version / family
            for family in ctx.config.release.packs.families
        }
        destination = ctx.storage.get("s3_release")
        if not destination:
            raise ValueError("Configure storage.s3_release before publication")
        result = publish(
            inventory(dataset, packs, version),
            destination,
            version,
            ctx.config.release.publish,
            dry_run=False,
        )
        receipt = (
            located(ctx.root, ctx.config.paths.work)
            / "releases"
            / version
            / "publish.json"
        )
        write_json(receipt, result)
        return [receipt]

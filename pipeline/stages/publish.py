"""Publish the completed dataset and requested client packs, then retain a receipt.

The target is fsspec (storage.s3_release) or GitHub Releases (release.publish.github).
"""

from dataclasses import asdict
from pathlib import Path
from typing import cast

from pipeline.release import github
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
        settings = ctx.config.release.publish
        destination = (
            f"github:{settings.github.repository}"
            if settings.target == "github"
            else ctx.storage.get("s3_release", "")
        )
        return [
            self.unit(
                ctx,
                version,
                {
                    "version": version,
                    "destination": destination,
                    "options": cast(Object, asdict(settings)),
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
        work = located(ctx.root, ctx.config.paths.work) / "releases" / version
        entries = inventory(dataset, packs, version)
        settings = ctx.config.release.publish
        if settings.target == "github":
            result = github.publish(
                entries,
                dataset,
                version,
                settings,
                dry_run=False,
                work=work,
                guard=ctx.guard,
            )
        else:
            destination = ctx.storage.get("s3_release")
            if not destination:
                raise ValueError("Configure storage.s3_release before publication")
            result = publish(entries, destination, version, settings, dry_run=False)
        receipt = work / "publish.json"
        write_json(receipt, result)
        return [receipt]

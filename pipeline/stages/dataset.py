"""Publish verified normalized cells and lookups as versioned Parquet tables."""

from dataclasses import asdict
from pathlib import Path
from typing import cast

from pipeline.release import pins as release_pins
from pipeline.release.assemble import assemble
from pipeline.release.metadata import licences, template_identity
from pipeline.release.source import Snapshot
from pipeline.release.verify import verify_dataset
from pipeline.runtime.jsonio import Object, sha256_file
from pipeline.runtime.paths import located
from pipeline.runtime.records import Dependency

from .contract import Context, Unit
from .engine_io import artifact
from .release import ReleaseStage


class DatasetStage(ReleaseStage):
    def parameters(self, ctx: Context) -> Object:
        values = asdict(ctx.config.release)
        for name in ("packs", "publish", "enabled", "region"):
            values.pop(name)
        # Source licences are content inputs; download budgets and URLs are not.
        contributors = {
            name
            for name, source in ctx.config.sources.items()
            if source.enabled
            and source.kind
            not in {"registration_evidence", "registration_country_evidence"}
        }
        previous = ctx.config.release.previous_version
        previous_hash = None
        if previous:
            directory = located(ctx.root, ctx.config.paths.dataset) / previous
            verify_dataset(directory)
            previous_hash = sha256_file(directory / "content.json")
        return cast(
            Object,
            {
                **values,
                "templates": template_identity(ctx.config),
                "licences": licences(ctx.config, contributors),
                "previous_digest": previous_hash,
            },
        )

    def units(self, ctx: Context) -> list[Unit]:
        if not ctx.config.release.enabled:
            return []
        return [
            self.unit(
                ctx,
                ctx.config.release.version,
                self.parameters(ctx),
                (Dependency("lookups", "manifest/current"),),
            )
        ]

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        self.check_writable(ctx)
        release_pins.verify(
            ctx.root, ctx.config.paths.normalized, release_pins.selected(ctx.config)
        )
        manifest = artifact(ctx, "lookups", "manifest/current", suffix="manifest.json")
        snapshot = Snapshot.read(ctx.root, manifest, ctx.config.h3)
        directory = located(ctx.root, ctx.config.paths.dataset)
        previous = (
            directory / ctx.config.release.previous_version
            if ctx.config.release.previous_version
            else None
        )
        return assemble(
            snapshot,
            directory / ctx.config.release.version,
            ctx.config,
            ctx.guard,
            unit.inputs_hash,
            previous,
        )

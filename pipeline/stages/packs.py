"""Build core before forward packs, accept each with the real reader, then index."""

from dataclasses import asdict
from pathlib import Path
from typing import cast

from pipeline.release import acceptance, bundle, client, samples
from pipeline.runtime.jsonio import Object
from pipeline.runtime.paths import located
from pipeline.runtime.records import Dependency

from .contract import Context, Unit
from .release import ReleaseStage


class PacksStage(ReleaseStage):
    def units(self, ctx: Context) -> list[Unit]:
        if not ctx.config.release.enabled:
            return []
        version = ctx.config.release.version
        families = ctx.config.release.packs.families
        if families and "core" not in families:
            raise ValueError("Forward pack releases must include the core family")
        checks: Object = {
            # Thresholds, sample sizes and the shared vectors decide acceptance.
            "acceptance": cast(Object, asdict(ctx.config.release.acceptance)),
            "vectors": samples.vectors_digest(),
        }
        units = [
            self.unit(
                ctx,
                f"{version}/{family}",
                {"family": family, "version": version, **checks},
                (Dependency("dataset", version),)
                + (
                    ()
                    if family == "core"
                    else (Dependency("packs", f"{version}/core"),)
                ),
            )
            for family in families
        ]
        if families:
            units.append(
                self.unit(
                    ctx,
                    f"{version}/index",
                    {"version": version},
                    tuple(
                        Dependency("packs", f"{version}/{family}")
                        for family in families
                    ),
                )
            )
        return units

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        self.check_writable(ctx)
        version, family = unit.recipe.unit_id.split("/")
        root = located(ctx.root, ctx.config.paths.packs) / version
        if family == "index":
            return [bundle.index(root, version, ctx.config.release.packs.families)]
        dataset = located(ctx.root, ctx.config.paths.dataset) / version
        output = root / family
        paths = client.write(dataset, family, output, version, client.binding())
        # A pack the reader cannot serve correctly is never archived.
        report = acceptance.accept(
            dataset, root, family, version, ctx.config.release.acceptance, ctx.log
        )
        return [*paths, report, bundle.archive(output, ctx.guard)]

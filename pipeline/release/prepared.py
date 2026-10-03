"""Run packs against a verified, separately prepared dataset without upstream work."""

from dataclasses import replace
from pathlib import Path

from pipeline.config import Config
from pipeline.runtime.context import context
from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.paths import located
from pipeline.runtime.runner import run
from pipeline.stages.contract import Context, Unit
from pipeline.stages.packs import PacksStage
from pipeline.stages.release import ReleaseStage

from .verify import verify_dataset


class PreparedDataset(ReleaseStage):
    def units(self, ctx: Context) -> list[Unit]:
        version = ctx.config.release.version
        directory = located(ctx.root, ctx.config.paths.dataset) / version
        verify_dataset(directory)
        return [
            self.unit(
                ctx,
                version,
                {"manifest_sha256": sha256_file(directory / "manifest.json")},
                (),
            )
        ]

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        directory = located(ctx.root, ctx.config.paths.dataset) / unit.recipe.unit_id
        manifest = verify_dataset(directory)
        return [directory / r["path"] for r in manifest["files"]] + [
            directory / "manifest.json"
        ]


def packs(config: Config, root: Path) -> dict[str, int]:
    """Only the prepared dataset, client writer and local runner are eligible."""
    settings = {stage.name: stage for stage in config.stages}
    stages = [
        PreparedDataset(replace(settings["dataset"], needs=[])),
        PacksStage(settings["packs"]),
    ]
    with Ledger(
        root,
        located(root, config.paths.ledger),
        readonly=False,
        timeout=config.resources.ledger_timeout_seconds,
    ) as ledger:
        ctx = context(config, root, ledger)
        ctx.readonly = False
        return run(ctx, stages, only="packs")

"""Build plate-country inference from explicitly enabled pinned evidence."""

from pathlib import Path

from pipeline.engines.plate_country import build
from pipeline.engines.reconcile.common import Row
from pipeline.runtime.paths import located

from . import engine_io as io
from .contract import Context, Unit
from .engine_data import source_manifest


def run(ctx: Context, unit: Unit) -> list[Path]:
    base = source_manifest(ctx, "plates")
    if base is None:
        raise ValueError("Missing normalized registration evidence")
    manifest = source_manifest(ctx, "plate_country")
    if manifest is None:
        raise ValueError("Missing normalized plate-country evidence")
    evidence = io.receipt(ctx, "normalize", "plate_country", suffix="sources.json")
    sources: dict[str, Row] = {
        record["name"]: {
            **record["upstream"],
            "path": str(located(ctx.root, record["path"])),
        }
        for record in evidence["sources"]
    }
    output = (
        located(ctx.root, ctx.config.paths.cells) / "plate_country" / unit.inputs_hash
    )
    return build.build(
        ctx.root,
        output,
        io.local(ctx, base),
        sources,
        ctx.config.engines.limits.parquet_batch_rows,
    )


def finish(ctx: Context) -> None:
    """The stage is absent until its frozen source is explicitly enabled."""

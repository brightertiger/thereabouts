"""Build plate-country inference from explicitly enabled pinned evidence."""

from pathlib import Path

from pipeline.engines.plate_country import build
from pipeline.engines.plate_country.policy import DATA
from pipeline.engines.plate_country.policy import policy as plate_policy
from pipeline.engines.reconcile.common import Row
from pipeline.runtime.paths import located

from . import engine_io as io
from . import parameters as unit_parameters
from .contract import Context, Unit
from .engine_data import Geography, source_manifest


def run(ctx: Context, unit: Unit) -> list[Path]:
    base = source_manifest(ctx, ctx.config.engines.registration_source)
    if base is None:
        raise ValueError("Missing normalized registration evidence")
    manifest = source_manifest(ctx, ctx.config.engines.plate_country_source)
    if manifest is None:
        raise ValueError("Missing normalized plate-country evidence")
    evidence = io.receipt(
        ctx, "normalize", ctx.config.engines.plate_country_source, suffix="sources.json"
    )
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


def parameters(ctx: Context, geography: Geography) -> unit_parameters.Configure:
    policy = {
        path.stem: plate_policy(path.stem) for path in sorted(DATA.glob("*.yaml"))
    }
    select = unit_parameters.constant(policy)
    limits = ctx.config.engines.limits
    return unit_parameters.prepare(
        select,
        geography,
        country_bytes=limits.country_reservation_bytes,
        block_bytes=limits.block_reservation_bytes,
    )

"""Build the writer's plate tables from pinned registration and plate-country evidence."""

from pathlib import Path

from pipeline.engines.plate_country import build, documents
from pipeline.engines.plate_country.policy import DATA, base_policy
from pipeline.engines.plate_country.policy import policy as plate_policy
from pipeline.engines.reconcile.common import Row
from pipeline.runtime.paths import located

from . import engine_io as io
from . import parameters as unit_parameters
from .contract import Context, Unit
from .engine_data import Geography, source_manifest


def run(ctx: Context, unit: Unit) -> list[Path]:
    settings = ctx.config.engines
    base = source_manifest(ctx, settings.registration_source)
    if base is None:
        raise ValueError("Missing normalized registration evidence")
    extra: list[Row] = []
    source = ctx.config.sources.get(settings.plate_country_source)
    if source is not None and source.enabled:
        evidence = io.receipt(
            ctx, "normalize", settings.plate_country_source, suffix="sources.json"
        )
        extra = evidence["sources"]
    pins = documents.pool(ctx.root, base, extra, settings.plate_country_source)
    output = (
        located(ctx.root, ctx.config.paths.cells) / "plate_country" / unit.inputs_hash
    )
    return build.build(
        ctx.root, output, io.local(ctx, base), pins, settings.limits.parquet_batch_rows
    )


def finish(ctx: Context) -> None:
    """The stage is absent until the registration source is normalized."""


def parameters(ctx: Context, geography: Geography) -> unit_parameters.Configure:
    policy = {
        path.stem: plate_policy(path.stem) for path in sorted(DATA.glob("*.yaml"))
    } | {"base_formats": base_policy("formats")}
    select = unit_parameters.constant(policy)
    limits = ctx.config.engines.limits
    return unit_parameters.prepare(
        select,
        geography,
        country_bytes=limits.country_reservation_bytes,
        block_bytes=limits.block_reservation_bytes,
    )

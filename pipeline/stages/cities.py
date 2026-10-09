"""Build canonical city indexes, mappings and a country manifest."""

from pathlib import Path
from typing import cast

from pipeline.engines.artifact_io import parquet
from pipeline.engines.cities import build, mapping, schemas
from pipeline.engines.cities.engine import Engine
from pipeline.engines.cities.urban import Urban
from pipeline.engines.store.codec import Row
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.paths import located

from . import engine_io as io
from . import parameters as unit_parameters
from .contract import Context, Unit
from .engine_data import Geography, countries, source_manifest
from .reconcile import country_policy


def urban(ctx: Context) -> Urban:
    manifest = source_manifest(ctx, ctx.config.engines.urban_source)
    if manifest is None:
        raise ValueError("Missing configured urban evidence")
    return Urban(io.local(ctx, manifest["partitions"]))


def engine(
    ctx: Context, cc: str, policy: Row, centres: Urban, *, land: bool = False
) -> Engine:
    index = io.artifact(ctx, "cities", "country/" + cc, suffix="index.sqlite")
    source = io.artifact(ctx, "reconcile", "country/" + cc, suffix=".sqlite")
    physical = None
    if land:
        physical = (
            io.artifact(ctx, "reconcile", "land/world", suffix=".sqlite"),
            country_policy(source, ctx.config.engines.limits.sqlite_cache_kib)[
                "offshore_m"
            ],
        )
    return Engine(
        index, source, centres, policy, physical, limits=ctx.config.engines.limits
    )


def run(ctx: Context, unit: Unit) -> list[Path]:
    action, _, key = unit.recipe.unit_id.partition("/")
    policy = cast(Row, unit.recipe.parameters["policy"])
    root = located(ctx.root, ctx.config.paths.cities) / unit.inputs_hash
    limits = ctx.config.engines.limits
    if action == "country":
        source = io.artifact(ctx, "reconcile", "country/" + key, suffix=".sqlite")
        report = build.build_country(
            ctx.root,
            root / key,
            key,
            source,
            urban(ctx),
            policy,
            limits,
        )
        return [
            located(ctx.root, report[name]["path"]) for name in ("index", "table")
        ] + [root / key / "report.json"]
    if action == "mapping":
        path = root / "place_to_city" / f"{key}.parquet"
        selector = engine(ctx, key, policy, urban(ctx))
        parquet(
            ctx.root,
            path,
            mapping.rows(selector, limits.mapping_batch_rows),
            schemas.MAPPING,
            limits.parquet_batch_rows,
        )
        return [path]
    if action == "manifest":
        path = root / "manifest.json"
        write_json(
            path,
            {
                "completed": True,
                "policy": policy,
                "countries": {
                    cc: io.receipt(ctx, "cities", "country/" + cc, suffix="report.json")
                    for cc in countries(ctx)
                },
                "mappings": [
                    io.table(
                        ctx, "cities", "mapping/" + cc, "place_to_city", country=cc
                    )
                    for cc in countries(ctx)
                ],
            },
        )
        return [path]
    raise ValueError(f"Unknown cities action: {action}")


def finish(ctx: Context) -> None:
    """Country publication validates its index, targets and Parquet cardinality."""


def parameters(ctx: Context, geography: Geography) -> unit_parameters.Configure:
    select = unit_parameters.country_policy(unit_parameters.cities(ctx), geography)
    limits = ctx.config.engines.limits
    return unit_parameters.prepare(
        select,
        geography,
        country_bytes=limits.country_reservation_bytes,
        block_bytes=limits.block_reservation_bytes,
    )

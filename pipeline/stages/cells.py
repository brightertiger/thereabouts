"""Build immutable base cells, canonical entities and their verified inventory."""

from pathlib import Path
from typing import cast

from pipeline.engines.artifact_io import file_record, parquet
from pipeline.engines.cells import build, inventory, places, schemas
from pipeline.engines.cells.inputs import Inputs
from pipeline.engines.reconcile.common import Row
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.paths import located

from . import engine_io as io
from . import parameters as unit_parameters
from . import reconcile
from .contract import Context, Unit
from .engine_data import Geography, countries, source_manifest


def inputs(ctx: Context, codes: list[str], policy: Row) -> Inputs:
    paths = reconcile.country_paths(ctx, codes)
    physical = io.artifact(ctx, "reconcile", "land/world", suffix=".sqlite")
    if paths:
        policy = reconcile.country_policy(
            next(iter(paths.values())), ctx.config.engines.limits.sqlite_cache_kib
        )
    return Inputs(
        {cc: {"path": str(path)} for cc, path in paths.items()},
        {"path": str(physical)},
        policy,
        set(codes),
        limits=ctx.config.engines.limits,
        grid=ctx.config.h3,
    )


def run(ctx: Context, unit: Unit) -> list[Path]:
    action, _, key = unit.recipe.unit_id.partition("/")
    policy = cast(Row, unit.recipe.parameters["policy"])
    settings = ctx.config.engines
    root = located(ctx.root, ctx.config.paths.cells) / "base" / unit.inputs_hash
    if action == "plan":
        sources = {}
        for source in settings.reconcile_sources:
            if source == settings.land_source:
                continue
            manifest = source_manifest(ctx, source)
            if manifest is None:
                raise ValueError(f"Missing normalized source: {source}")
            kind = (
                "places"
                if ctx.config.sources[source].kind == "places_and_names"
                else "areas"
            )
            sources[source] = [
                str(located(ctx.root, row["path"]))
                for row in manifest["partitions"]
                if row["kind"] == kind
            ]
        value = inventory.inventory(
            sources,
            policy,
            ctx.config.resources,
            settings.limits,
            {name: ctx.config.sources[name].kind for name in sources},
        )
        destination = located(ctx.root, settings.country_inventory)
        blocks = located(ctx.root, settings.block_index)
        inventory.index(
            blocks, value, policy, ctx.config.h3, settings.blocks, settings.limits
        )
        write_json(destination, value)
        return [destination, blocks]
    if action == "block":
        codes = cast(list[str], unit.recipe.parameters["countries"])
        rows, statistics = build.build(
            int(key, 16), inputs(ctx, codes, policy), codes, log=ctx.log
        )
        path = root / "cells" / f"{key}.parquet"
        record = parquet(
            ctx.root, path, rows, schemas.CELLS, settings.limits.parquet_batch_rows
        )
        receipt = root / f"{key}.json"
        write_json(
            receipt, {"table": {**record, "kind": "cells", "block": key}, **statistics}
        )
        return [path, receipt]
    if action == "places":
        country_source = io.artifact(
            ctx, "reconcile", "country/" + key, suffix=".sqlite"
        )
        path = root / "places" / f"{key}.parquet"
        parquet(
            ctx.root,
            path,
            places.entities(
                country_source,
                reconcile.country_policy(
                    country_source, settings.limits.sqlite_cache_kib
                ),
                settings.limits.sqlite_cache_kib,
            ),
            schemas.PLACES,
            settings.limits.parquet_batch_rows,
        )
        return [path]
    if action == "manifest":
        tables = []
        for dependency in unit.recipe.dependencies:
            kind, _, name = dependency.unit_id.partition("/")
            kind = "cells" if kind == "block" else kind
            labels = {"block" if kind == "cells" else "country": name}
            tables.append(io.table(ctx, "cells", dependency.unit_id, kind, **labels))
        path = root / "manifest.json"
        write_json(
            path,
            {
                "completed": True,
                "tables": tables,
                "reference_resolution": ctx.config.h3.cell_resolution,
                "block_resolution": ctx.config.h3.block_resolution,
                "policy": policy,
                "countries": countries(ctx),
            },
        )
        return [path]
    if action == "snapshot":
        # Base tables are already immutable, so the snapshot owns metadata only.
        manifest = io.receipt(ctx, "cells", "manifest/current", suffix="manifest.json")
        path = root / "manifest.json"
        write_json(path, manifest)
        pointer = located(ctx.root, ctx.config.paths.cells) / "base" / "current.json"
        write_json(pointer, {"manifest": file_record(ctx.root, path)})
        return [path, pointer]
    raise ValueError(f"Unknown cells action: {action}")


def finish(ctx: Context) -> None:
    """Per-unit publication validates every base artifact before ledger completion."""


def parameters(ctx: Context, geography: Geography) -> unit_parameters.Configure:
    policy = unit_parameters.reconciliation(ctx)
    select = unit_parameters.constant(policy)
    limits = ctx.config.engines.limits
    return unit_parameters.prepare(
        select,
        geography,
        country_bytes=limits.country_reservation_bytes,
        block_bytes=limits.block_reservation_bytes,
        refresh_plan=True,
    )

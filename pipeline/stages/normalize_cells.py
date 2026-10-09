"""Normalize base cells and place catalogues, then measure stored country output."""

import shutil
from pathlib import Path
from typing import cast

from pipeline.engines import query
from pipeline.engines.artifact_io import parquet
from pipeline.engines.artifacts import EVALUATION, read_json
from pipeline.engines.cells.inputs import Inputs
from pipeline.engines.cells.reader import Cells
from pipeline.engines.cells.schemas import CELLS
from pipeline.engines.cities.evaluate import Comparison
from pipeline.engines.cities.quality import country_report, named_checks
from pipeline.engines.normalize_cells import blocks, tables
from pipeline.engines.reconcile.common import Row
from pipeline.runtime.jsonio import atomic_output, write_json
from pipeline.runtime.paths import located

from . import cities
from . import engine_io as io
from . import parameters as unit_parameters
from .contract import Context, Unit
from .engine_data import Geography
from .engine_views import Engines


def run(ctx: Context, unit: Unit) -> list[Path]:
    action, _, key = unit.recipe.unit_id.partition("/")
    policy = cast(Row, unit.recipe.parameters["policy"])
    root = located(ctx.root, ctx.config.paths.cells) / "normalized" / unit.inputs_hash
    limits = ctx.config.engines.limits
    if action == "block":
        base = io.table(ctx, "cells", "block/" + key, "cells", block=key)
        centres = cities.urban(ctx)
        engines = Engines(
            ctx, cast(list[str], unit.recipe.parameters["countries"]), policy, centres
        )
        rows, counts = blocks.transform(
            io.local(ctx, base),
            engines,
            policy["town_radius"]["enabled"],
            grid=ctx.config.h3,
        )
        path = root / "cells" / f"{key}.parquet"
        record = parquet(ctx.root, path, rows, CELLS, limits.parquet_batch_rows)
        receipt = root / f"{key}.json"
        write_json(
            receipt,
            {"table": {**record, "kind": "cells", "block": key}, "countries": counts},
        )
        return [path, receipt]
    if action == "places":
        base_path = io.artifact(ctx, "cells", "places/" + key, suffix=".parquet")
        mapping = io.artifact(ctx, "cities", "mapping/" + key, suffix=".parquet")
        canonical = io.artifact(
            ctx, "cities", "country/" + key, suffix="canonical_cities.parquet"
        )
        outputs = []
        for kind, source in (
            ("place_to_city", mapping),
            ("canonical_cities", canonical),
        ):
            destination = root / kind / f"{key}.parquet"
            with atomic_output(destination) as temporary:
                shutil.copyfile(source, temporary)
            outputs.append(destination)
        path = root / "places" / f"{key}.parquet"
        db = query.connect(root / "spill", ctx.config.resources, limits)
        try:
            tables.places(
                db, base_path, mapping, canonical, path, limits.join_row_group_rows
            )
        finally:
            db.close()
        return [path, *outputs]
    if action == "quality":
        views: dict[str, list[Row]] = {"cells": [], "normalize_cells": []}
        for dependency in unit.recipe.dependencies:
            if not dependency.unit_id.startswith("block/"):
                continue
            name = dependency.unit_id.removeprefix("block/")
            views[dependency.stage].append(
                io.local(
                    ctx,
                    io.table(
                        ctx, dependency.stage, dependency.unit_id, "cells", block=name
                    ),
                )
            )
        comparison = Comparison(
            Cells(views["cells"], limits, grid=ctx.config.h3),
            {},
            policy["town_radius"]["enabled"],
            Cells(views["normalize_cells"], limits, grid=ctx.config.h3),
        )
        centres = cities.urban(ctx)
        report = country_report(
            comparison,
            key,
            cities.engine(ctx, key, policy, centres),
            centres,
            read_json(EVALUATION / "cities/probes.json"),
        )
        source = io.artifact(ctx, "reconcile", "country/" + key, suffix=".sqlite")
        inputs = Inputs(
            {key: {"path": str(source)}},
            {},
            {},
            grid=ctx.config.h3,
            limits=ctx.config.engines.limits,
        )
        report["named"] = [
            row for row in named_checks(comparison, inputs) if row["country"] == key
        ]
        path = root / f"{key}-quality.json"
        write_json(path, report)
        return [path]
    raise ValueError(f"Unknown normalization action: {action}")


def finish(ctx: Context) -> None:
    """Final cross-country gates run in lookups after all country checks complete."""


def parameters(ctx: Context, geography: Geography) -> unit_parameters.Configure:
    select = unit_parameters.country_policy(unit_parameters.cities(ctx), geography)
    limits = ctx.config.engines.limits
    return unit_parameters.prepare(
        select,
        geography,
        country_bytes=limits.country_reservation_bytes,
        block_bytes=limits.block_reservation_bytes,
        reads={"quality": unit_parameters.CITY_EVIDENCE},
    )

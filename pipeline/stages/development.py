"""Score only the development split against the actual city transformation."""

import csv
from pathlib import Path

import h3

from pipeline.engines.cells.reader import Cells
from pipeline.engines.cities.evaluate import Comparison
from pipeline.engines.normalize_cells.score import grade
from pipeline.engines.store.codec import Row
from pipeline.engines.store.database import connect
from pipeline.engines.store.entities import find_entity

from . import cities
from .contract import Context
from .engine_views import Engines
from .reconcile import country_paths


def score(
    ctx: Context, points: Path, base: list[Row], policy: Row, codes: list[str]
) -> Row:
    with points.open(newline="", encoding="utf-8") as stream:
        selected = [r for r in csv.DictReader(stream) if r["split"] == "dev"]
    if not selected:
        raise ValueError("Development evaluation has no points")
    cells = [
        h3.latlng_to_cell(
            float(r["latitude"]), float(r["longitude"]), ctx.config.h3.cell_resolution
        )
        for r in selected
    ]
    engines = Engines(ctx, codes, policy, cities.urban(ctx))
    before, after = Comparison(
        Cells(base, ctx.config.engines.limits, grid=ctx.config.h3),
        engines,
        policy["town_radius"]["enabled"],
    ).query(cells)
    names: dict[str, Row] = {}
    for cc, path in country_paths(ctx, codes).items():
        ids = {
            row["city_id"]
            for row in [*before, *after]
            if row.get("city_id") and row.get("country_id") == "country:" + cc
        }
        if not ids:
            continue
        db = connect(
            path, readonly=True, cache_kib=ctx.config.engines.limits.sqlite_cache_kib
        )
        try:
            for identity in ids:
                value = find_entity(db, identity)
                if value:
                    names[identity] = {**value, "wikidata_ids": []}
        finally:
            db.close()
    return {
        "before": grade(selected, cells, before, names),
        "after": grade(selected, cells, after, names),
    }

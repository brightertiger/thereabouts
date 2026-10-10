"""All population-15k source points; exact and explicitly supported roll-up credit."""

from collections import Counter

import h3

from pipeline.engines.artifacts import EVALUATION, read_json
from pipeline.engines.store.catalog import geonames_places
from pipeline.engines.store.codec import Row
from pipeline.engines.store.database import connect

from .engine import Engine
from .evaluate import Comparison


def checks(comparison: Comparison, engine: Engine) -> Row:
    db = connect(engine.source, readonly=True, cache_kib=engine.limits.sqlite_cache_kib)
    try:
        places = list(geonames_places(db, "P", 15000))
    finally:
        db.close()
    cells = [
        h3.latlng_to_cell(
            p["latitude"], p["longitude"], comparison.before.grid.cell_resolution
        )
        for p in places
    ]
    before, after = comparison.query(cells)
    overrides = read_json(EVALUATION / "cities/diagnostic_expectations.json")[
        "overrides"
    ]
    counts: Counter[str] = Counter()
    changes = []
    for p, b, a in zip(places, before, after, strict=True):
        identity = "city:geonames:" + p["source_id"]
        expected = overrides.get(identity, identity)
        counts["total"] += 1
        for prefix, row in [("before", b), ("after", a)]:
            counts[prefix + "_exact"] += row.get("city_id") == identity
            counts[prefix + "_credited"] += row.get("city_id") == expected
        if b.get("city_id") != a.get("city_id"):
            changes.append(
                {
                    "id": identity,
                    "name": p["name"],
                    "feature_code": p["feature_code"],
                    "population": p["population"],
                    "h3": h3.latlng_to_cell(
                        p["latitude"],
                        p["longitude"],
                        comparison.before.grid.cell_resolution,
                    ),
                    "expected": expected,
                    "before": b,
                    "after": a,
                    "gain": b.get("city_id") != expected
                    and a.get("city_id") == expected,
                    "loss": b.get("city_id") == expected
                    and a.get("city_id") != expected,
                }
            )
    return {"counts": dict(counts), "changes": changes}

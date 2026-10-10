"""Revisit the plan's 130 failed anchors using current pipeline sources and rules."""

import h3

from pipeline.engines.artifacts import EVALUATION, read_json
from pipeline.engines.store.catalog import geonames_point
from pipeline.engines.store.codec import Row
from pipeline.engines.store.database import connect

from .engine import Engine
from .evaluate import Comparison


def audit(comparison: Comparison, country: str, engine: Engine) -> list[Row]:
    reference = read_json(EVALUATION / "cities/regressions.json")
    result = []
    db = connect(engine.source, readonly=True, cache_kib=engine.limits.sqlite_cache_kib)
    try:
        for probe in reference["points"]:
            if probe["country"] != country:
                continue
            point = geonames_point(db, probe["id"])
            if point is None:
                result.append(
                    {"probe": probe, "error": "missing acquired GeoNames point"}
                )
                continue
            cell = h3.latlng_to_cell(
                point[1], point[0], comparison.before.grid.cell_resolution
            )
            before, after = comparison.query([cell])
            identity = "city:geonames:" + probe["id"]
            target = engine.parts.get(identity, identity)
            result.append(
                {
                    "probe": probe,
                    "h3": cell,
                    "before": before[0],
                    "after": after[0],
                    "retained_exact": after[0].get("city_id") == identity,
                    "retained_or_policy_rollup": after[0].get("city_id") == target,
                    "policy_target": target,
                }
            )
    finally:
        db.close()
    return result

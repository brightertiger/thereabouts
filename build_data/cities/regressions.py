"""Revisit the plan's 130 failed anchors using current pipeline sources and rules."""

from pathlib import Path

import h3

from build_data.acquire.artifacts import read_json
from build_data.reconcile.common import Row, connect

from .engine import Engine
from .evaluate import Comparison


def audit(comparison: Comparison, country: str, engine: Engine) -> list[Row]:
    reference = read_json(Path(__file__).with_suffix(".json"))
    result = []
    db = connect(engine.source, readonly=True)
    try:
        for probe in reference["points"]:
            if probe["country"] != country:
                continue
            point = db.execute(
                "SELECT x,y FROM geonames WHERE id=?", (probe["id"],)
            ).fetchone()
            if point is None:
                result.append(
                    {"probe": probe, "error": "missing acquired GeoNames point"}
                )
                continue
            cell = h3.latlng_to_cell(point[1], point[0], 8)
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

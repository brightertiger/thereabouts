"""Audit original accepted boundaries, before overlap subtraction or city roll-up."""

from collections import Counter

import h3
import shapely

from build_data.reconcile.common import Row, connect, unpack

from .engine import Engine
from .evaluate import Comparison, measure


def boundary_checks(comparison: Comparison, cc: str, engine: Engine) -> list[Row]:
    """Detect each lost interior cell, even when gains elsewhere hide a net loss.

    This census uses the original accepted geometry, not the effective footprint
    that the assignment rule constructs. Owner-approved roll-ups are credited and
    reported separately. Overlap losses remain visible for review.
    """
    result = []
    db = connect(engine.index_path, readonly=True)
    try:
        for blob, metadata in db.execute(
            "SELECT geometry,data FROM boundaries ORDER BY id"
        ):
            boundary = unpack(metadata)
            shape = shapely.from_wkb(blob)
            cells = sorted(h3.geo_to_cells(shape.__geo_interface__, 8))
            before, after = comparison.query(cells)
            selected = [
                i
                for i, r in enumerate(before)
                if r.get("country_id") == f"country:{cc}"
            ]
            owner, target = boundary["city_id"], boundary["target_id"]
            lost = [
                i
                for i in selected
                if before[i].get("city_id") == owner
                and after[i].get("city_id") != target
            ]
            rollups = (
                sum(
                    before[i].get("city_id") == owner
                    and after[i].get("city_id") == target
                    for i in selected
                )
                if owner != target
                else 0
            )
            result.append(
                {
                    "country": cc,
                    "city_id": owner,
                    "target_id": target,
                    "references": boundary["references"],
                    "method": boundary["method"],
                    "before": measure([before[i] for i in selected], owner),
                    "after": measure([after[i] for i in selected], target),
                    "policy_rollup_cells": rollups,
                    "lost_cells": len(lost),
                    "lost_to": dict(
                        Counter(str(after[i].get("city_id")) for i in lost)
                    ),
                    "loss_examples": [
                        {"h3": cells[i], "after": after[i].get("city_id")}
                        for i in lost[:10]
                    ],
                }
            )
    finally:
        db.close()
    return result

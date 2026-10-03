"""Audit original accepted boundaries, before overlap subtraction or city roll-up."""

from collections import Counter

import h3
import shapely

from pipeline.engines.reconcile.common import Row, connect, unpack

from .engine import Engine
from .evaluate import Comparison, measure


def boundary_checks(comparison: Comparison, cc: str, engine: Engine) -> list[Row]:
    """Detect each lost interior cell, even when gains elsewhere hide a net loss.

    This census uses the original accepted geometry, not the effective footprint
    that the assignment rule constructs. Owner-approved roll-ups are credited and
    reported separately. Overlap losses remain visible for review.
    """
    result = []
    aliases = engine.policy["countries"].get(cc, {}).get("identity_aliases", {})
    db = connect(
        engine.index_path, readonly=True, cache_kib=engine.limits.sqlite_cache_kib
    )
    try:
        for blob, metadata in db.execute(
            "SELECT geometry,data FROM boundaries ORDER BY id"
        ):
            boundary = unpack(metadata)
            shape = shapely.from_wkb(blob)
            cells = sorted(
                h3.geo_to_cells(
                    shape.__geo_interface__, comparison.before.grid.cell_resolution
                )
            )
            before, after = comparison.query(cells)
            selected = [
                i
                for i, r in enumerate(before)
                if r.get("country_id") == f"country:{cc}"
            ]
            owner, target = boundary["city_id"], boundary["target_id"]
            owners = {
                owner,
                *(a for a, canonical in aliases.items() if canonical == owner),
            }
            owned_before = measure([before[i] for i in selected], owner)
            owned_before["expected"] = sum(
                owned_before["answers"].get(i, 0) for i in owners
            )
            owned_before["share"] = (
                owned_before["expected"] / owned_before["eligible"]
                if owned_before["eligible"]
                else None
            )
            lost = [
                i
                for i in selected
                if before[i].get("city_id") in owners
                and after[i].get("city_id") != target
            ]
            rollups = (
                sum(
                    before[i].get("city_id") in owners
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
                    "before": owned_before,
                    "before_owner_ids": sorted(owners),
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

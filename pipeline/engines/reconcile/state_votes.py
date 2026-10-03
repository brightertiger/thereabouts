"""Auditable admin1 crosswalk evidence from small places inside a state."""

from __future__ import annotations

import sqlite3
from collections import Counter

import numpy as np
import shapely

from .common import Row
from .spatial import decode


def votes(
    db: sqlite3.Connection,
    identity: str,
    policy: Row,
    batch_rows: int,
) -> Row:
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    for (wkb,) in db.execute(
        "SELECT geometry FROM areas WHERE role='state' AND entity=?", (identity,)
    ):
        geometry = decode(wkb)
        xmin, ymin, xmax, ymax = geometry.bounds
        cursor = db.execute(
            "SELECT id,admin1,x,y FROM geonames WHERE class='P' "
            "AND coalesce(population,0)<? AND admin1 IS NOT NULL "
            "AND x>=? AND x<=? AND y>=? AND y<=?",
            (policy["minimum_population"], xmin, xmax, ymin, ymax),
        )
        while batch := cursor.fetchmany(batch_rows):
            xy = np.array([(r[2], r[3]) for r in batch])
            mask = shapely.intersects_xy(geometry, xy[:, 0], xy[:, 1])
            for (source_id, code, _, _), inside in zip(batch, mask, strict=True):
                if inside and source_id not in seen:
                    seen.add(source_id)
                    counts[code] += 1
    ranked = sorted(counts.items(), key=lambda v: (-v[1], v[0]))
    total = sum(counts.values())
    confidence = ranked[0][1] / total if total else 0.0
    accepted = (
        total >= policy["state_vote_minimum"]
        and confidence >= policy["state_vote_fraction"]
    )
    return {
        "geonames_admin1": ranked[0][0] if accepted else None,
        "method": "dominant admin1 among contained P places below 15,000 population",
        "evidence_counts": dict(ranked),
        "confidence": confidence,
        "large_places_excluded": True,
    }

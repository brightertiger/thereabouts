"""Disconnected seam envelopes and bounded SQLite reads across both seam copies."""

from __future__ import annotations

import math
import sqlite3

from pipeline.engines.reconcile.spatial import EARTH_M, intersecting

from .geometry import Floats

Bounds = tuple[float, float, float, float]
Area = tuple[int, str, str, int, bytes, bytes | str]


def envelopes(coordinates: Floats) -> list[Bounds]:
    groups = [coordinates]
    if coordinates[:, 1].max() - coordinates[:, 1].min() > 180:
        groups = [
            coordinates[coordinates[:, 1] < 0],
            coordinates[coordinates[:, 1] >= 0],
        ]
    return [
        (
            float(c[:, 1].min()),
            float(c[:, 0].min()),
            float(c[:, 1].max()),
            float(c[:, 0].max()),
        )
        for c in groups
        if len(c)
    ]


def expanded(bounds: Bounds, offshore_m: float) -> list[Bounds]:
    w, s, e, n = bounds
    dy = math.degrees(offshore_m * 1.02 / EARTH_M) + 1e-4
    dx = min(
        360.0, dy / max(1e-8, math.cos(math.radians(min(90, max(abs(s), abs(n)) + dy))))
    )
    result = []
    for shift in (-360, 0, 360):
        left, right = max(-180, w - dx + shift), min(180, e + dx + shift)
        if left <= right:
            result.append((left, right, max(-90, s - dy), min(90, n + dy)))
    return result


def areas(
    db: sqlite3.Connection, windows: list[Bounds], role: str | None = None
) -> list[Area]:
    if len(windows) == 1:
        return list(intersecting(db, windows[0], role))
    found = {r[0]: r for window in windows for r in intersecting(db, window, role)}
    if role is None or not found:
        return list(found.values())
    # Preserve the scalar R-tree traversal order across the union. Read only
    # IDs from the broad envelope, never all its geometries and entity blobs.
    query = (
        "SELECT r.id FROM area_bounds r JOIN areas a ON a.id=r.id "
        "WHERE r.xmin<=? AND r.xmax>=? AND r.ymin<=? AND r.ymax>=? AND a.role=?"
    )
    args = (
        max(w[1] for w in windows),
        min(w[0] for w in windows),
        max(w[3] for w in windows),
        min(w[2] for w in windows),
        role,
    )
    return [found[i] for (i,) in db.execute(query, args) if i in found]

"""Exact place coverage, and reproducible equal-area land sampling with error."""

from __future__ import annotations

import math
import sqlite3

import numpy as np
import shapely

from .common import Row
from .land import Land
from .spatial import decode, intersecting


def place_coverage(db: sqlite3.Connection) -> Row:
    covered = 0
    country_covered = 0
    total = 0
    # Process each populated degree tile. The R-tree supplies candidate area
    # parts; vector predicates limit memory even for very populous countries.
    tiles = db.execute(
        "SELECT DISTINCT CAST(floor(x) AS INT),CAST(floor(y) AS INT) "
        "FROM geonames WHERE class='P'"
    ).fetchall()
    for x, y in tiles:
        points = db.execute(
            "SELECT x,y FROM geonames WHERE class='P' "
            "AND x>=? AND x<? AND y>=? AND y<?",
            (x, x + 1, y, y + 1),
        ).fetchall()
        if not points:
            continue
        array = np.array(points)
        mask = np.zeros(len(points), dtype=bool)
        country_mask = np.zeros(len(points), dtype=bool)
        for _, _, _, _, wkb, _ in intersecting(db, (x, x + 1, y, y + 1), "city"):
            mask |= shapely.intersects_xy(decode(wkb), array[:, 0], array[:, 1])
        for _, _, _, _, wkb, _ in intersecting(db, (x, x + 1, y, y + 1), "country"):
            country_mask |= shapely.intersects_xy(decode(wkb), array[:, 0], array[:, 1])
        total += len(points)
        covered += int(mask.sum())
        country_covered += int(country_mask.sum())
    return {
        "total": total,
        "covered": covered,
        "percent": 100 * covered / total if total else None,
        "country_covered": country_covered,
        "country_not_covered": total - country_covered,
        "definition": (
            "All GeoNames P records, including sub-city/historical records; "
            "exact polygon containment at their points"
        ),
    }


def land_coverage(db: sqlite3.Connection, land: Land, samples: int = 20000) -> Row:
    # Stratification in (longitude, sin(latitude)) gives equal spherical area.
    # A fixed seed makes the estimate reproducible; never call this exact area.
    country_parts = list(intersecting(db, (-180, 180, -90, 90), "country"))
    if not country_parts:
        return {"percent": None, "reason": "No country geometry"}
    geometries = [decode(r[4]) for r in country_parts]
    bounds = shapely.total_bounds(geometries)
    xmin, ymin, xmax, ymax = (float(v) for v in bounds)
    rng = np.random.default_rng(20261001)
    x = rng.uniform(xmin, xmax, samples)
    y = np.degrees(
        np.arcsin(
            rng.uniform(
                math.sin(math.radians(ymin)), math.sin(math.radians(ymax)), samples
            )
        )
    )
    belongs = np.zeros(samples, dtype=bool)
    for geometry in geometries:
        belongs |= shapely.intersects_xy(geometry, x, y)
    inside = covered = 0
    # Group samples into tiles and run vector predicates against bounded pieces.
    tiles: dict[tuple[int, int], list[int]] = {}
    for i in np.flatnonzero(belongs):
        tiles.setdefault((math.floor(x[i]), math.floor(y[i])), []).append(int(i))
    for (a, b), indices in tiles.items():
        xs, ys = x[indices], y[indices]
        land_mask = np.zeros(len(indices), dtype=bool)
        city_mask = np.zeros(len(indices), dtype=bool)
        for _, _, _, _, wkb, _ in intersecting(land.db, (a, a + 1, b, b + 1)):
            land_mask |= shapely.intersects_xy(decode(wkb), xs, ys)
        for _, _, _, _, wkb, _ in intersecting(db, (a, a + 1, b, b + 1), "city"):
            city_mask |= shapely.intersects_xy(decode(wkb), xs, ys)
        inside += int(land_mask.sum())
        covered += int((land_mask & city_mask).sum())
    p = covered / inside if inside else 0.0
    # Wilson score interval remains nonzero at 0%/100%.
    z, n = 1.96, max(1, inside)
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {
        "percent": 100 * p if inside else None,
        "land_samples": inside,
        "covered_samples": covered,
        "confidence_95_percent": [
            100 * max(0, center - half),
            100 * min(1, center + half),
        ],
        "method": (
            "20,000 uniform spherical-area samples in country bbox, seed 20261001; "
            "physical OSM land intersected with country. Estimate, not exact area."
        ),
    }

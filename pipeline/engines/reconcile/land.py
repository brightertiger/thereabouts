"""Physical land and the bounded offshore band, independent of jurisdiction."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import shapely

from pipeline.config.engines import EngineLimits
from pipeline.engines.geo.sphere import EARTH_M
from pipeline.engines.geo.windows import windows
from pipeline.engines.store.areas import insert_area, intersecting
from pipeline.engines.store.codec import rows
from pipeline.engines.store.database import check_database, connect
from pipeline.engines.store.schema import create_areas
from pipeline.runtime.jsonio import atomic_output
from pipeline.runtime.paths import located

from .spatial import containing


def build_land(
    root: Path, paths: list[str], output: Path, limits: EngineLimits
) -> Path:
    with atomic_output(output) as temp:
        db = connect(temp, cache_kib=limits.sqlite_cache_kib)
        try:
            create_areas(db)
            for index, path in enumerate(paths):
                for row in rows(located(root, path), limits.source_batch_rows):
                    insert_area(
                        db,
                        row["source_id"],
                        "land",
                        0,
                        row["geometry"],
                        tuple(row[k] for k in ("xmin", "ymin", "xmax", "ymax")),
                        path,
                    )
                db.commit()
                if index % 100 == 0:
                    print(f"land {index + 1}/{len(paths)}", flush=True)
        finally:
            db.close()
        check_database(temp, limits.sqlite_cache_kib)
    return output


def nearest_spherical(wkb: bytes, x: float, y: float) -> tuple[float, float, float]:
    """Nearest on great-circle segments; no fixed-degree coastal buffer.

    Polygon boundaries are short source segments. Ring-closing edges and holes
    are retained. Artificial partition edges cannot create a nearer exterior
    shore: each candidate point is itself land, and containment is tested first.
    """
    geometry = shapely.from_wkb(wkb)
    rings = [
        ring
        for polygon in shapely.get_parts(geometry)
        for ring in shapely.get_rings(polygon)
    ]
    best = (math.inf, x, y)
    lon, lat = math.radians(x), math.radians(y)
    p = np.array(
        [math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)]
    )
    for ring in rings:
        coords = np.radians(shapely.get_coordinates(ring))
        vectors = np.column_stack(
            (
                np.cos(coords[:, 1]) * np.cos(coords[:, 0]),
                np.cos(coords[:, 1]) * np.sin(coords[:, 0]),
                np.sin(coords[:, 1]),
            )
        )
        a, b = vectors[:-1], vectors[1:]
        n = np.cross(a, b)
        norm = np.linalg.norm(n, axis=1)
        good = norm > 1e-15
        n[good] /= norm[good, None]
        foot = p - np.sum(n * p, axis=1)[:, None] * n
        size = np.linalg.norm(foot, axis=1)
        good &= size > 1e-15
        foot[good] /= size[good, None]
        inside = (
            good
            & (np.sum(np.cross(a, foot) * n, axis=1) >= 0)
            & (np.sum(np.cross(foot, b) * n, axis=1) >= 0)
        )
        candidates = np.concatenate((vectors, foot[inside]))
        angles = np.arctan2(
            np.linalg.norm(np.cross(candidates, p), axis=1), candidates @ p
        )
        i = int(np.argmin(angles))
        q = candidates[i]
        value = (
            float(angles[i]) * EARTH_M,
            math.degrees(math.atan2(q[1], q[0])),
            math.degrees(math.asin(float(q[2]))),
        )
        best = min(best, value)
    return best


class Land:
    def __init__(self, path: Path, limits: EngineLimits) -> None:
        self.db = connect(path, readonly=True, cache_kib=limits.sqlite_cache_kib)

    def close(self) -> None:
        self.db.close()

    def project(
        self, x: float, y: float, cutoff: float
    ) -> tuple[float, float, str, float] | None:
        if next(containing(self.db, x, y), None):
            return x, y, "land", 0.0
        best = (math.inf, x, y)
        for bounds in windows((x, y, x, y), cutoff * 1.01):
            for _, _, _, _, wkb, _ in intersecting(self.db, bounds):
                best = min(best, nearest_spherical(wkb, x, y))
        d, a, b = best
        if d <= cutoff:
            return a, b, "offshore", d
        return None

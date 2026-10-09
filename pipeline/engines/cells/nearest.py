"""Bounded country point indexes and exact scalar handling at numerical ties."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from pipeline.config.engines import EngineLimits
from pipeline.engines.cache import Cache
from pipeline.engines.geo.arrays import FloatArray, IntArray
from pipeline.engines.geo.sphere import EARTH_M, distance, unit_vectors
from pipeline.engines.reconcile.common import connect


class Nearest:
    def __init__(self, path: Path, limits: EngineLimits) -> None:
        db = connect(path, readonly=True, cache_kib=limits.sqlite_cache_kib)
        try:
            records = db.execute(
                "SELECT DISTINCT entity,x,y FROM points ORDER BY entity,x,y"
            ).fetchall()
        finally:
            db.close()
        self.ids = [r[0] for r in records]
        self.coordinates = np.array(
            [(r[2], r[1]) for r in records], dtype=np.float64
        ).reshape((-1, 2))
        self.xyz = unit_vectors(self.coordinates)
        self.tree = cKDTree(self.xyz) if len(records) else None

    def query(
        self, coordinates: FloatArray, cutoff: float
    ) -> tuple[IntArray, FloatArray, FloatArray]:
        n = len(coordinates)
        if self.tree is None:
            return (
                np.full(n, -1, dtype=np.int64),
                np.full(n, np.inf),
                np.full(n, np.inf),
            )
        xyz = unit_vectors(coordinates)
        chords, indices = self.tree.query(xyz, k=2)
        chosen = indices[:, 0].astype(np.int64)
        lat, lon = np.radians(coordinates).T
        other_lat, other_lon = np.radians(self.coordinates[chosen]).T
        h = (
            np.sin((other_lat - lat) / 2) ** 2
            + np.cos(lat) * np.cos(other_lat) * np.sin((other_lon - lon) / 2) ** 2
        )
        first = 2 * EARTH_M * np.arcsin(np.sqrt(np.minimum(1, h)))
        second = np.where(
            np.isfinite(chords[:, 1]),
            2 * EARTH_M * np.arcsin(np.minimum(1, chords[:, 1] / 2)),
            np.inf,
        )
        exceptional = np.flatnonzero(
            (second - first < 1e-6) | (np.abs(first - cutoff) < 1e-6)
        )
        for i in exceptional:
            candidates = self.tree.query_ball_point(xyz[i], float(chords[i, 0]) + 1e-12)
            y, x = coordinates[i]
            d, _, selected = min(
                (
                    distance(x, y, self.coordinates[j, 1], self.coordinates[j, 0]),
                    self.ids[j],
                    j,
                )
                for j in candidates
            )
            first[i], chosen[i] = d, selected
        chosen[first > cutoff] = -1
        return chosen, first, second


_cache: Cache[tuple[Path, int, int], Nearest] = Cache()


def nearest(path: Path, limits: EngineLimits) -> Nearest:
    stamp = path.stat()
    return _cache.get(
        (path, stamp.st_size, stamp.st_mtime_ns),
        lambda: Nearest(path, limits),
        limits.nearest_cache_entries,
    )

"""Prepared polygon membership retaining the scalar oracle's candidate order."""

from __future__ import annotations

from functools import partial
from typing import Any, cast

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely import STRtree
from shapely.geometry.base import BaseGeometry

from pipeline.config.engines import EngineLimits
from pipeline.engines.cache import Cache
from pipeline.engines.geo.arrays import FloatArray, IntArray
from pipeline.engines.reconcile.classification import city_order
from pipeline.engines.store.codec import Row


def _large_geometry(wkb: bytes) -> BaseGeometry:
    value = shapely.from_wkb(wkb)
    shapely.prepare(value)
    return value


# Prepared geometries are built lazily inside GEOS; concurrent units each keep
# their own, since sharing one between threads can crash the process.
_geometries: Cache[bytes, BaseGeometry] = Cache(per_thread=True)


def geometry(wkb: bytes, limits: EngineLimits) -> BaseGeometry:
    if len(wkb) >= limits.large_geometry_bytes:
        return _geometries.get(
            wkb, lambda: _large_geometry(wkb), limits.geometry_cache_entries
        )
    value = shapely.from_wkb(wkb)
    shapely.prepare(value)
    return value


def _edge_index(wkb: bytes, limits: EngineLimits) -> STRtree:
    lines: list[BaseGeometry] = []
    for polygon in shapely.get_parts(geometry(wkb, limits)):
        for ring in shapely.get_rings(polygon):
            coordinates = shapely.get_coordinates(ring)
            lines.extend(
                shapely.LineString(
                    coordinates[start : start + limits.edge_segments + 1]
                )
                for start in range(0, len(coordinates) - 1, limits.edge_segments)
            )
    return STRtree(lines)


_edges: Cache[tuple[bytes, int], STRtree] = Cache(per_thread=True)


def boundaries(
    sources: list[bytes],
    bounds: tuple[float, float, float, float],
    limits: EngineLimits,
) -> STRtree:
    lines = []
    region = shapely.box(*bounds)
    for wkb in sources:
        tree = (
            _edges.get(
                (wkb, limits.edge_segments),
                partial(_edge_index, wkb, limits),
                limits.geometry_cache_entries,
            )
            if len(wkb) >= limits.large_geometry_bytes
            else _edge_index(wkb, limits)
        )
        selected = tree.query(region, predicate="intersects")
        lines.extend(tree.geometries[selected].tolist())
    return STRtree(lines)


class Areas:
    def __init__(self, shapes: list[BaseGeometry], records: list[Row]) -> None:
        self.tree = STRtree(shapes)
        self.records = records
        identities = {s: i for i, s in enumerate(sorted({r["id"] for r in records}))}
        self.identities = np.array(
            [identities[r["id"]] for r in records], dtype=np.int64
        )
        self.priority = np.array([r["priority"] for r in records], dtype=np.int64)
        self.country = np.array([r["cc"] for r in records], dtype=object)
        keys = []
        for shape, r in zip(shapes, records, strict=True):
            key: tuple[Any, ...]
            if r["role"] == "country":
                key = (-r["priority"], shape.area, r["cc"])
            elif r["role"] == "state":
                key = (0, shape.area, r["id"])
            else:
                key = city_order(r, r["priority"], shape.area)
            keys.append(key)
        order = sorted(range(len(keys)), key=lambda i: keys[i])
        self.order = np.array(order, dtype=np.int64)
        self.rank = np.argsort(self.order)

    def winners(
        self, coordinates: FloatArray, countries: NDArray[np.object_] | None = None
    ) -> IntArray:
        result = np.full(len(coordinates), -1, dtype=np.int64)
        if not len(self.records) or not len(coordinates):
            return result
        points = cast(
            NDArray[np.object_], shapely.points(coordinates[:, 1], coordinates[:, 0])
        )
        pairs = self.tree.query(points)
        if not pairs.size:
            return result
        p, g = pairs
        keep = shapely.covers(self.tree.geometries[g], points[p])
        if countries is not None:
            keep &= self.country[g] == countries[p]
        p, g = p[keep], g[keep]
        # covering() keeps the first geometry at the highest priority for an
        # entity, then applies the role's ranking across distinct entities.
        order = np.lexsort((g, -self.priority[g], self.identities[g], p))
        p, g = p[order], g[order]
        first = (
            np.r_[
                True,
                (p[1:] != p[:-1]) | (self.identities[g[1:]] != self.identities[g[:-1]]),
            ]
            if len(p)
            else np.zeros(0, dtype=bool)
        )
        best = np.full(len(coordinates), len(self.records), dtype=np.int64)
        np.minimum.at(best, p[first], self.rank[g[first]])
        found = best < len(self.records)
        result[found] = self.order[best[found]]
        return result


def inside(tree: STRtree, coordinates: FloatArray) -> NDArray[np.bool_]:
    points = cast(
        NDArray[np.object_], shapely.points(coordinates[:, 1], coordinates[:, 0])
    )
    pairs = tree.query(points)
    result = np.zeros(len(points), dtype=np.bool_)
    if pairs.size:
        keep = shapely.covers(tree.geometries[pairs[1]], points[pairs[0]])
        result[pairs[0, keep]] = True
    return cast(NDArray[np.bool_], result)

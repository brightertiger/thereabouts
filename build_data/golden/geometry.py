"""Prepared polygon membership retaining the scalar oracle's candidate order."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely import STRtree
from shapely.geometry.base import BaseGeometry

from build_data.reconcile.common import Row

Floats = NDArray[np.float64]
Ints = NDArray[np.int64]


@lru_cache(maxsize=24)
def _large_geometry(wkb: bytes) -> BaseGeometry:
    value = shapely.from_wkb(wkb)
    shapely.prepare(value)
    return value


def geometry(wkb: bytes) -> BaseGeometry:
    if len(wkb) >= 100_000:
        return _large_geometry(wkb)
    value = shapely.from_wkb(wkb)
    shapely.prepare(value)
    return value


def _edge_index(wkb: bytes) -> STRtree:
    lines: list[BaseGeometry] = []
    for polygon in shapely.get_parts(geometry(wkb)):
        for ring in shapely.get_rings(polygon):
            coordinates = shapely.get_coordinates(ring)
            lines.extend(
                shapely.LineString(coordinates[start : start + 65])
                for start in range(0, len(coordinates) - 1, 64)
            )
    return STRtree(lines)


_large_edges = lru_cache(maxsize=24)(_edge_index)


def boundaries(
    sources: list[bytes], bounds: tuple[float, float, float, float]
) -> STRtree:
    lines = []
    region = shapely.box(*bounds)
    for wkb in sources:
        tree = _large_edges(wkb) if len(wkb) >= 100_000 else _edge_index(wkb)
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
                key = (
                    -r["priority"],
                    -(r["population"] or 0) if r["geonames_id"] else 0,
                    shape.area,
                    r["id"],
                )
            keys.append(key)
        order = sorted(range(len(keys)), key=lambda i: keys[i])
        self.order = np.array(order, dtype=np.int64)
        self.rank = np.argsort(self.order)

    def winners(
        self, coordinates: Floats, countries: NDArray[np.object_] | None = None
    ) -> Ints:
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


def inside(tree: STRtree, coordinates: Floats) -> NDArray[np.bool_]:
    points = cast(
        NDArray[np.object_], shapely.points(coordinates[:, 1], coordinates[:, 0])
    )
    pairs = tree.query(points)
    result = np.zeros(len(points), dtype=np.bool_)
    if pairs.size:
        keep = shapely.covers(tree.geometries[pairs[1]], points[pairs[0]])
        result[pairs[0, keep]] = True
    return cast(NDArray[np.bool_], result)

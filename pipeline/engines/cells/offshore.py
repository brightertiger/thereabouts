"""Exact great-circle segment candidates, bounded by spherical midpoint caps."""

from __future__ import annotations

import math

import numpy as np
import shapely
from numpy.typing import NDArray
from scipy.spatial import cKDTree
from shapely.geometry.base import BaseGeometry

from pipeline.config.engines import EngineLimits
from pipeline.engines.reconcile.spatial import EARTH_M

from .geometry import Floats, Ints


class Offshore:
    def __init__(
        self,
        shapes: list[BaseGeometry],
        owner_bounds: Floats,
        batch_rows: int = EngineLimits.offshore_batch_rows,
    ) -> None:
        self.batch_rows = batch_rows
        left, right, owners = [], [], []
        for owner, shape in enumerate(shapes):
            for polygon in shapely.get_parts(shape):
                for ring in shapely.get_rings(polygon):
                    coordinates = np.radians(shapely.get_coordinates(ring))
                    vectors = np.column_stack(
                        (
                            np.cos(coordinates[:, 1]) * np.cos(coordinates[:, 0]),
                            np.cos(coordinates[:, 1]) * np.sin(coordinates[:, 0]),
                            np.sin(coordinates[:, 1]),
                        )
                    )
                    left.append(vectors[:-1])
                    right.append(vectors[1:])
                    owners.extend([owner] * (len(vectors) - 1))
        self.a = np.concatenate(left) if left else np.empty((0, 3))
        self.b = np.concatenate(right) if right else np.empty((0, 3))
        self.owners = np.array(owners, dtype=np.int64)
        self.bounds = owner_bounds
        cross = np.cross(self.a, self.b)
        length = np.linalg.norm(cross, axis=1)
        self.good = length > 1e-15
        self.normal = cross.copy()
        self.normal[self.good] /= length[self.good, None]
        angle = np.arctan2(length, np.sum(self.a * self.b, axis=1))
        centre = self.a + self.b
        norm = np.linalg.norm(centre, axis=1)
        valid = norm > 1e-15
        centre[valid] /= norm[valid, None]
        centre[~valid] = self.a[~valid]
        radius = angle / 2
        radius[~valid] = np.pi
        bucket = np.ceil(np.log2(np.maximum(1.0, radius * EARTH_M))).astype(np.int64)
        self.trees: list[tuple[Ints, float, cKDTree]] = []
        for key in np.unique(bucket):
            indices = np.flatnonzero(bucket == key)
            self.trees.append(
                (indices, float(radius[indices].max()), cKDTree(centre[indices]))
            )

    def pairs(self, vectors: Floats, cutoff: float) -> tuple[Ints, Ints]:
        points, segments = [], []
        for indices, radius, tree in self.trees:
            chord = 2 * np.sin(min(np.pi, radius + cutoff / EARTH_M + 1e-12) / 2)
            matches = tree.query_ball_point(vectors, float(chord) + 1e-12)
            counts = np.fromiter((len(m) for m in matches), dtype=np.int64)
            if counts.sum():
                points.append(
                    np.repeat(np.arange(len(vectors), dtype=np.int64), counts)
                )
                segments.append(
                    indices[
                        np.concatenate(
                            [np.asarray(m, dtype=np.int64) for m in matches if len(m)]
                        )
                    ]
                )
        if not points:
            return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
        return np.concatenate(points), np.concatenate(segments)

    def project(
        self, coordinates: Floats, cutoff: float
    ) -> tuple[Floats, NDArray[np.bool_], NDArray[np.bool_]]:
        output = coordinates.copy()
        eligible = np.zeros(len(coordinates), dtype=np.bool_)
        exceptional = np.zeros(len(coordinates), dtype=np.bool_)
        # A very detailed coast can have thousands of short segments per query.
        # Bound the cross-product arrays independently of the r3 block size.
        for start in range(0, len(coordinates), self.batch_rows):
            stop = min(start + self.batch_rows, len(coordinates))
            output[start:stop], eligible[start:stop], exceptional[start:stop] = (
                self._project(coordinates[start:stop], cutoff)
            )
        return output, eligible, exceptional

    def _project(
        self, coordinates: Floats, cutoff: float
    ) -> tuple[Floats, NDArray[np.bool_], NDArray[np.bool_]]:
        # Use the scalar query vector construction; source segment vectors use
        # the identical NumPy construction as nearest_spherical().
        vectors = np.array(
            [
                (
                    math.cos(math.radians(y)) * math.cos(math.radians(x)),
                    math.cos(math.radians(y)) * math.sin(math.radians(x)),
                    math.sin(math.radians(y)),
                )
                for y, x in coordinates
            ],
            dtype=np.float64,
        ).reshape((-1, 3))
        p, g = self.pairs(vectors, cutoff)
        output = coordinates.copy()
        eligible = np.zeros(len(coordinates), dtype=np.bool_)
        exceptional = np.zeros(len(coordinates), dtype=np.bool_)
        if not len(p):
            return output, eligible, exceptional
        # Match the scalar oracle's SQLite R-tree candidate window, including
        # outward-rounded float32 bounds and both copies of the date seam.
        y, x = coordinates[p].T
        w, e, s, n = self.bounds[self.owners[g]].T
        dy = math.degrees(cutoff * 1.01 / EARTH_M)
        dx = np.minimum(
            180.0,
            dy / np.maximum(0.000001, np.cos(np.radians(np.minimum(90, abs(y) + dy)))),
        )
        longitude = np.zeros(len(p), dtype=np.bool_)
        for shift in (-360, 0, 360):
            longitude |= (w <= x + dx + shift) & (e >= x - dx + shift)
        keep = longitude & (s <= y + dy) & (n >= y - dy)
        p, g = p[keep], g[keep]
        if not len(p):
            return output, eligible, exceptional
        query, normal = vectors[p], self.normal[g]
        foot = query - np.sum(normal * query, axis=1)[:, None] * normal
        size = np.linalg.norm(foot, axis=1)
        good = self.good[g] & (size > 1e-15)
        foot[good] /= size[good, None]
        inside = (
            good
            & (np.sum(np.cross(self.a[g], foot) * normal, axis=1) >= 0)
            & (np.sum(np.cross(foot, self.b[g]) * normal, axis=1) >= 0)
        )
        candidates = np.stack((self.a[g], self.b[g], foot), axis=1)
        angles = np.arctan2(
            np.linalg.norm(np.cross(candidates, query[:, None, :]), axis=2),
            np.sum(candidates * query[:, None, :], axis=2),
        )
        angles[~inside, 2] = np.inf
        selected = np.argmin(angles, axis=1)
        distances = angles[np.arange(len(p)), selected] * EARTH_M
        projected = candidates[np.arange(len(p)), selected]
        order = np.lexsort((g, distances, p))
        first = np.r_[True, p[order[1:]] != p[order[:-1]]]
        best = order[first]
        close = distances[best] <= cutoff
        chosen, destinations = projected[best[close]], p[best[close]]
        eligible[destinations] = True
        output[destinations, 0] = np.degrees(np.arcsin(np.clip(chosen[:, 2], -1, 1)))
        output[destinations, 1] = np.degrees(np.arctan2(chosen[:, 1], chosen[:, 0]))
        exceptional[p[best[np.abs(distances[best] - cutoff) < 1e-5]]] = True
        # Distinct equidistant projections require scalar ring/geometry ordering.
        minimum = np.full(len(coordinates), np.inf)
        minimum[p[best]] = distances[best]
        near = abs(distances - minimum[p]) < 1e-5
        direction = np.zeros((len(coordinates), 3))
        direction[p[best]] = projected[best]
        exceptional[
            p[near & (np.linalg.norm(projected - direction[p], axis=1) > 1e-12)]
        ] = True
        return output, eligible, exceptional

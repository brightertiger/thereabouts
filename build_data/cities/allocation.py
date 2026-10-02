"""Divide unclaimed built-up cells among cities whose municipal extent is unknown."""

from typing import cast

import numpy as np
from numpy.typing import NDArray

from build_data.reconcile.common import Row
from build_data.reconcile.spatial import EARTH_M
from build_data.reference.sphere import unit_vectors

from .radius import assign
from .urban import Urban

Floats = NDArray[np.float64]
Objects = NDArray[np.object_]


class Allocation:
    """Population-weighted urban allocation, constrained by known boundaries.

    A bounded city cannot spread past its limits and swallow an unbounded neighbour.
    An unbounded town retains its local core; elsewhere distance is scaled by the
    square root of population. These are inferred extents, not legal boundaries.
    """

    def __init__(
        self, cities: list[Row], footprints: list[Row], urban: Urban, policy: Row
    ) -> None:
        self.urban, self.policy = urban, policy
        self.ids = np.array([r["city_id"] for r in cities], dtype=object)
        coordinates = np.array(
            [(r["latitude"], r["longitude"]) for r in cities], dtype=np.float64
        ).reshape((-1, 2))
        self.xyz = unit_vectors(coordinates)
        self.pop = np.array([r["population"] for r in cities], dtype=np.float64)
        self.clusters = urban.anchors(coordinates, policy["anchor_urban_edge_m"])
        bounded = {r["city_id"] for r in footprints}
        self.unbounded = np.array([i not in bounded for i in self.ids], dtype=bool)

    def divide(
        self, coordinates: Floats, ids: Objects, methods: Objects
    ) -> NDArray[np.int64]:
        """Fill only unclaimed cells within the same connected urban centre."""
        clusters = self.urban.locate(coordinates)
        xyz = unit_vectors(coordinates)
        unclaimed = ids == None  # noqa: E711
        for cluster in np.unique(clusters[unclaimed & (clusters >= 0)]):
            selected = np.flatnonzero((clusters == cluster) & unclaimed)
            candidates = np.flatnonzero((self.clusters == cluster) & self.unbounded)
            if not len(candidates):
                continue
            for start in range(0, len(selected), 1024):
                rows = selected[start : start + 1024]
                distances = spherical_distances(xyz[rows], self.xyz[candidates])
                nearest = np.argmin(distances, axis=1)
                population_scale = np.sqrt(
                    np.maximum(self.policy["population_floor"], self.pop[candidates])
                )
                weighted = np.argmin(distances / population_scale, axis=1)
                near_core = (
                    distances[np.arange(len(rows)), nearest] <= self.policy["core_m"]
                )
                chosen = np.where(near_core, nearest, weighted)
                ids[rows] = self.ids[candidates[chosen]]
                methods[rows] = "urban_allocation"
        return clusters

    def radii(
        self,
        coordinates: Floats,
        clusters: NDArray[np.int64],
        ids: Objects,
        methods: Objects,
    ) -> None:
        """Optionally claim rural cells reached by a qualifying town's own radius."""
        settings = self.policy["town_radius"]
        candidates = np.flatnonzero(
            self.unbounded
            & (self.clusters < 0)
            & (self.pop <= settings["maximum_population"])
        )
        rows = np.flatnonzero((clusters < 0) & (ids == None))  # noqa: E711
        chosen = assign(
            coordinates[rows],
            self.xyz[candidates],
            self.pop[candidates],
            self.ids[candidates],
            settings,
        )
        hit = chosen != None  # noqa: E711
        ids[rows[hit]], methods[rows[hit]] = chosen[hit], "town_radius"


def spherical_distances(points: Floats, anchors: Floats) -> Floats:
    """Bound the temporary distance matrix to one urban centre and one row batch."""
    squared_chord = np.maximum(0, 2 - 2 * points @ anchors.T)
    half_chord = np.minimum(1, np.sqrt(squared_chord) / 2)
    return cast(Floats, 2 * EARTH_M * np.arcsin(half_chord))

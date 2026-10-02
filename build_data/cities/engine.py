"""City boundaries, same-country urban allocation and optional small-town radius."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
import shapely
from numpy.typing import NDArray

from build_data.golden.nearest import nearest
from build_data.reconcile.common import Row, connect, unpack
from build_data.reconcile.spatial import EARTH_M
from build_data.reference.sphere import unit_vectors

from .projection import project
from .rural import rural
from .urban import Urban

Objects = NDArray[np.object_]
Floats = NDArray[np.float64]


class Engine:
    def __init__(
        self,
        path: Path,
        source: Path,
        urban: Urban,
        policy: Row,
        land: tuple[Path, float] | None = None,
    ) -> None:
        self.land = land
        self.source, self.urban, self.policy = source, urban, policy
        db = connect(path, readonly=True)
        try:
            self.cities = [
                unpack(b) for (b,) in db.execute("SELECT data FROM cities ORDER BY id")
            ]
            self.footprints = [
                {**unpack(b), "geometry": shapely.from_wkb(g)}
                for b, g in db.execute(
                    "SELECT data,geometry FROM footprints ORDER BY id"
                )
            ]
            self.parts = dict(db.execute("SELECT place_id,city_id FROM parts"))
            self.rejected = {i for (i,) in db.execute("SELECT area_id FROM rejected")}
            self.repair_ids = {
                i for (i,) in db.execute("SELECT DISTINCT city_id FROM rejected")
            }
        finally:
            db.close()
        self.ids = np.array([r["city_id"] for r in self.cities], dtype=object)
        self.city_state = next(
            (i for i in self.ids if i.startswith("city:country:")), None
        )
        self.coordinates = np.array(
            [(r["latitude"], r["longitude"]) for r in self.cities], dtype=np.float64
        ).reshape((-1, 2))
        self.xyz = unit_vectors(self.coordinates)
        self.pop = np.array([r["population"] for r in self.cities], dtype=np.float64)
        self.clusters = urban.anchors(self.coordinates, policy["anchor_urban_edge_m"])
        bounded = {r["city_id"] for r in self.footprints}
        self.unbounded = np.array([i not in bounded for i in self.ids], dtype=bool)
        self.tree = shapely.STRtree([r["geometry"] for r in self.footprints])
        self.order = np.array(
            sorted(
                range(len(self.footprints)),
                key=lambda i: (
                    self.footprints[i]["priority"],
                    self.footprints[i]["geometry"].area,
                    self.footprints[i]["city_id"],
                ),
            ),
            dtype=np.int64,
        )
        self.rank = np.argsort(self.order)

    def polygons(self, coordinates: Floats) -> NDArray[np.int64]:
        points = shapely.points(coordinates[:, 1], coordinates[:, 0])
        pairs = self.tree.query(points, predicate="intersects")
        ranks = np.full(len(coordinates), len(self.footprints), dtype=np.int64)
        if pairs.size:
            np.minimum.at(ranks, pairs[0], self.rank[pairs[1]])
        result = np.full(len(coordinates), -1, dtype=np.int64)
        hit = ranks < len(self.footprints)
        result[hit] = self.order[ranks[hit]]
        return result

    def overlay(self, coordinates: Floats, radius: bool) -> tuple[Objects, Objects]:
        ids = np.full(len(coordinates), None, dtype=object)
        methods = ids.copy()
        if self.city_state is not None:
            ids[:] = self.city_state
            methods[:] = "policy_polygon"
            return cast(Objects, ids), cast(Objects, methods)
        winners = self.polygons(coordinates)
        for i in np.unique(winners[winners >= 0]):
            mask = winners == i
            ids[mask] = self.footprints[i]["city_id"]
            methods[mask] = self.footprints[i]["method"]
        clusters = self.urban.locate(coordinates)
        xyz = unit_vectors(coordinates)
        for cluster in np.unique(clusters[(winners < 0) & (clusters >= 0)]):
            selected = np.flatnonzero((clusters == cluster) & (winners < 0))
            candidates = np.flatnonzero((self.clusters == cluster) & self.unbounded)
            if not len(candidates):
                continue
            for start in range(0, len(selected), 1024):
                rows = selected[start : start + 1024]
                # At most 1024 query rows by this one urban centre's anchors.
                distances = (
                    2
                    * EARTH_M
                    * np.arcsin(
                        np.minimum(
                            1,
                            np.sqrt(
                                np.maximum(
                                    0, 2 - 2 * xyz[rows] @ self.xyz[candidates].T
                                )
                            )
                            / 2,
                        )
                    )
                )
                close = np.argmin(distances, axis=1)
                weighted = np.argmin(
                    distances
                    / np.sqrt(
                        np.maximum(
                            self.policy["population_floor"], self.pop[candidates]
                        )
                    ),
                    axis=1,
                )
                chosen = np.where(
                    distances[np.arange(len(rows)), close] <= self.policy["core_m"],
                    close,
                    weighted,
                )
                ids[rows] = self.ids[candidates[chosen]]
                methods[rows] = "urban_allocation"
        if radius:
            self.radii(coordinates, clusters, ids, methods)
        return cast(Objects, ids), cast(Objects, methods)

    def radii(
        self,
        coordinates: Floats,
        clusters: NDArray[np.int64],
        ids: Objects,
        methods: Objects,
    ) -> None:
        from .radius import assign

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

    def apply(
        self,
        coordinates: Floats,
        before: Objects,
        before_methods: Objects,
        radius: bool,
        offshore: NDArray[np.bool_] | None = None,
    ) -> tuple[Objects, Objects]:
        projected = (
            project(self.land, coordinates, offshore)
            if offshore is not None
            else coordinates
        )
        ids, methods = self.overlay(projected, radius)
        missing = ids == None  # noqa: E711
        repair = (
            missing
            & (before_methods == "area")
            & np.isin(before, list(self.repair_ids))
        )
        if repair.any():
            db = connect(self.source, readonly=True)
            try:
                ids[repair], methods[repair] = rural(
                    self, db, coordinates[repair], projected[repair]
                )
            finally:
                db.close()
        preserve = missing & ~repair
        ids[preserve] = before[preserve]
        methods[preserve] = np.where(
            before_methods[preserve] == "area",
            "rural_polygon",
            before_methods[preserve],
        )
        nearest_rows = np.flatnonzero(preserve & (before_methods == "nearest"))
        if len(nearest_rows):
            _, distance, _ = nearest(self.source).query(
                coordinates[nearest_rows], self.policy["nearest_m"]
            )
            methods[nearest_rows] = np.where(
                distance > self.policy["distant_m"],
                "rural_nearest_distant",
                "rural_nearest",
            )
        for source, target in self.parts.items():
            hit = ids == source
            ids[hit] = target
        return ids, methods

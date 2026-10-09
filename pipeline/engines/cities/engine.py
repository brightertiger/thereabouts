"""City boundaries, same-country urban allocation and optional small-town radius."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
import shapely
from numpy.typing import NDArray

from pipeline.config.engines import EngineLimits
from pipeline.engines.cells.nearest import nearest
from pipeline.engines.geo.arrays import FloatArray
from pipeline.engines.reconcile.common import Row, connect, unpack

from .allocation import Allocation
from .boundaries import BoundaryIndex
from .projection import project
from .rural import rural
from .urban import Urban

Objects = NDArray[np.object_]


class Engine:
    """Apply city footprints, urban inference, then the retained rural answer.

    Country/state and land eligibility are inherited from the base cell stage.
    Rejected broad promotions are repaired before falling back to a village.
    """

    def __init__(
        self,
        path: Path,
        source: Path,
        urban: Urban,
        policy: Row,
        land: tuple[Path, float] | None = None,
        *,
        limits: EngineLimits,
    ) -> None:
        """Load a committed country index and build its two spatial selectors."""
        self.limits = limits
        self.index_path = path
        self.land = land
        self.source, self.urban, self.policy = source, urban, policy
        db = connect(path, readonly=True, cache_kib=self.limits.sqlite_cache_kib)
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
        self.boundaries = BoundaryIndex(self.footprints)
        self.allocation = Allocation(
            self.cities,
            self.footprints,
            urban,
            policy,
            self.limits.allocation_batch_rows,
        )

    def polygons(
        self, coordinates: FloatArray, tolerance: float = 0.0
    ) -> NDArray[np.int64]:
        """Choose an accepted boundary without expanding over nearby settlements."""
        return self.boundaries.query(coordinates, tolerance)

    def overlay(
        self, coordinates: FloatArray, radius: bool, tolerance: float = 0.0
    ) -> tuple[Objects, Objects]:
        """Known municipal limits win; inference fills the remaining urban cells."""
        ids = np.full(len(coordinates), None, dtype=object)
        methods = ids.copy()
        if self.city_state is not None:
            ids[:] = self.city_state
            methods[:] = "policy_polygon"
            return cast(Objects, ids), cast(Objects, methods)
        winners = self.polygons(coordinates, tolerance)
        for i in np.unique(winners[winners >= 0]):
            mask = winners == i
            ids[mask] = self.footprints[i]["city_id"]
            methods[mask] = self.footprints[i]["method"]
        clusters = self.allocation.divide(coordinates, ids, methods)
        if radius:
            self.allocation.radii(coordinates, clusters, ids, methods)
        return cast(Objects, ids), cast(Objects, methods)

    def apply(
        self,
        coordinates: FloatArray,
        before: Objects,
        before_methods: Objects,
        radius: bool,
        offshore: NDArray[np.bool_] | None = None,
    ) -> tuple[Objects, Objects]:
        """Retain rural answers unless a city extent or repair supersedes them."""
        projected = (
            project(self.land, coordinates, offshore, self.limits)
            if offshore is not None
            else coordinates
        )
        # Explicit city footprints own their original r8 centres, including water.
        # Project only otherwise unclaimed offshore cells before urban inference.
        inside = self.polygons(coordinates) >= 0
        projected[inside] = coordinates[inside]
        ids, methods = self.overlay(projected, radius)
        if offshore is not None:
            water = np.flatnonzero(offshore & ~inside)
            winners = self.polygons(
                projected[water], self.policy["projected_edge_tolerance_degrees"]
            )
            for i in np.unique(winners[winners >= 0]):
                hit = water[winners == i]
                ids[hit] = self.footprints[i]["city_id"]
                methods[hit] = self.footprints[i]["method"]
        missing = ids == None  # noqa: E711
        repair = (
            missing
            & (before_methods == "area")
            & np.isin(before, list(self.repair_ids))
        )
        if repair.any():
            db = connect(
                self.source, readonly=True, cache_kib=self.limits.sqlite_cache_kib
            )
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
            _, distance, _ = nearest(self.source, self.limits).query(
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

"""Lazy direct polygon index, isolated so future accelerators can precede it."""

from itertools import pairwise

import numpy as np
import shapely
from shapely import STRtree
from shapely.errors import GEOSException
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry

from thereabouts.errors import DamagedPackError

from .pack import Pack
from .schema import BOUNDARY_TOLERANCE_DEG


class PolygonIndex:
    def __init__(self, pack: Pack, layer: str) -> None:
        self.pack = pack
        self.layer = layer
        self._tree: STRtree | None = None

    def tree(self) -> STRtree:
        if self._tree is None:
            offsets = self.pack.arrays[f"{self.layer}_offsets"]
            blob = self.pack.arrays[f"{self.layer}_wkb"]
            parts: list[BaseGeometry] = []
            try:
                for start, stop in pairwise(offsets):
                    part = shapely.from_wkb(blob[int(start) : int(stop)].tobytes())
                    if (
                        part.geom_type != "Polygon"
                        or part.is_empty
                        or not part.is_valid
                    ):
                        raise ValueError("expected nonempty valid polygon")
                    if not np.isfinite(part.bounds).all():
                        raise ValueError("non-finite polygon bounds")
                    parts.append(part)
            except (GEOSException, ValueError, TypeError) as exc:
                raise DamagedPackError(f"Invalid {self.layer} geometry: {exc}") from exc
            shapely.prepare(parts)
            self._tree = STRtree(parts)
        return self._tree

    def query(self, lat: float, lon: float) -> tuple[int, ...]:
        tree = self.tree()
        shapes: list[BaseGeometry] = [Point(lon, lat)]
        tolerance = BOUNDARY_TOLERANCE_DEG
        if abs(lat) == 90:
            shapes = [LineString([(-180, lat), (180, lat)])]
        elif abs(lon) >= 180 - tolerance:
            shapes.append(Point(lon + (360 if lon < 0 else -360), lat))
        owners = self.pack.arrays[f"{self.layer}_owners"]
        matches: set[int] = set()
        for query in shapes:
            w, s, e, n = query.bounds
            candidates = tree.query(
                box(w - tolerance, s - tolerance, e + tolerance, n + tolerance)
            )
            for index in candidates:
                part = tree.geometries[index]
                if part.intersects(query) or part.distance(query) <= tolerance:
                    matches.add(int(owners[index]))
        return tuple(sorted(matches))

    def close(self) -> None:
        self._tree = None

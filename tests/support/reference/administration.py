"""Polygon membership and conservative boundary certificates for the builder."""

from typing import cast

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely import STRtree
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from .pack import Pack
from .polygons import PolygonIndex
from .schema import BOUNDARY_TOLERANCE_DEG as EPS

FloatArray = NDArray[np.float64]
BOUNDARY_SEGMENTS = 64
NO_MATCH = np.iinfo(np.int64).max


class Administration:
    def __init__(self, pack: Pack) -> None:
        self.pack = pack
        self.layers = {
            name: PolygonIndex(self.pack, name)
            for name in ("country", "admin1", "land")
        }
        self.ranks: dict[str, NDArray[np.int64]] = {}
        for layer, table in (("country", "countries"), ("admin1", "admin1")):
            ids = [self.pack.text(int(i)) for i in self.pack.arrays[table]["id"]]
            self.ranks[layer] = np.argsort(np.argsort(ids)).astype(np.int64)
        boundaries: list[BaseGeometry] = []
        self.edges: dict[str, tuple[STRtree, NDArray[np.int64]]] = {}
        for layer, index in self.layers.items():
            lines, owners = [], []
            for part, owner in zip(
                index.tree().geometries,
                self.pack.arrays[f"{layer}_owners"],
                strict=True,
            ):
                for ring in (part.exterior, *part.interiors):
                    coordinates = np.asarray(ring.coords)
                    for start in range(0, len(coordinates) - 1, BOUNDARY_SEGMENTS):
                        lines.append(
                            shapely.LineString(
                                coordinates[start : start + BOUNDARY_SEGMENTS + 1]
                            )
                        )
                        owners.append(int(owner))
            self.edges[layer] = STRtree(lines), np.array(owners, dtype=np.int64)
            boundaries.extend(lines)
        coverage = self.pack.manifest["coverage_bbox"]
        if coverage is not None:
            boundaries.append(box(*coverage).boundary)
        self.boundaries = STRtree(boundaries)

    def rows(self, coordinates: FloatArray, layer: str) -> NDArray[np.int64]:
        index = self.layers[layer]
        points = cast(
            NDArray[np.object_], shapely.points(coordinates[:, 1], coordinates[:, 0])
        )
        pairs = index.tree().query(points)
        if pairs.size:
            contained = shapely.intersects(
                index.tree().geometries[pairs[1]], points[pairs[0]]
            )
            pairs = pairs[:, contained]
        result = np.full(len(coordinates), NO_MATCH, dtype=np.int64)
        owners = self.pack.arrays[f"{layer}_owners"]
        ranks = self.ranks.get(layer, np.zeros(1, dtype=np.int64))
        if pairs.size:
            np.minimum.at(result, pairs[0], ranks[owners[pairs[1]]])
        edge_tree, edge_owners = self.edges[layer]
        edge_pairs = edge_tree.query(points, predicate="dwithin", distance=EPS)
        if edge_pairs.size:
            np.minimum.at(result, edge_pairs[0], ranks[edge_owners[edge_pairs[1]]])
        # The original engine checks both seam copies and treats pole longitude
        # as physically irrelevant. These rare rows use its scalar predicate.
        special = np.flatnonzero(
            (np.abs(coordinates[:, 1]) >= 180 - EPS) | (np.abs(coordinates[:, 0]) == 90)
        )
        for i in special:
            rows = index.query(*coordinates[i])
            result[i] = min((int(ranks[r]) for r in rows), default=NO_MATCH)
        found = result != NO_MATCH
        result[found] = np.argsort(ranks)[result[found]]
        result[~found] = -1
        return result

    def membership(
        self, coordinates: FloatArray
    ) -> tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.bool_]]:
        country = self.rows(coordinates, "country")
        state = self.rows(coordinates, "admin1")
        land = self.rows(coordinates, "land")
        present = (country >= 0) | (land >= 0)
        bounds = self.pack.manifest["coverage_bbox"]
        if bounds is not None:
            w, s, e, n = bounds
            lat, lon = coordinates.T
            present &= (w <= lon) & (lon <= e) & (s <= lat) & (lat <= n)
        return country, state, present

    def uniform(self, bounds: FloatArray) -> NDArray[np.bool_]:
        """No polygon edge, pole or seam may cross a descendant envelope."""
        w, s, e, n = bounds.T
        rectangles = shapely.box(w - 2 * EPS, s - 2 * EPS, e + 2 * EPS, n + 2 * EPS)
        pairs = self.boundaries.query(rectangles, predicate="intersects")
        result = np.ones(len(bounds), dtype=np.bool_)
        result[pairs[0]] = False
        result &= (w > -180 + EPS) & (e < 180 - EPS) & (s > -90 + EPS) & (n < 90 - EPS)
        return result

    def close(self) -> None:
        self.layers.clear()
        self.edges.clear()
        self.boundaries = STRtree([])

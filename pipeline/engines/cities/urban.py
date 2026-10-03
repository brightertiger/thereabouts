"""One small verified GHSL index, shared by country builders and cell workers."""

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import shapely
from numpy.typing import NDArray
from shapely.geometry.base import BaseGeometry

from pipeline.engines.reconcile.common import Row
from pipeline.engines.reconcile.spatial import distance


class Urban:
    def __init__(self, partitions: list[Row]) -> None:
        rows = [
            r for p in partitions for r in pq.read_table(Path(p["path"])).to_pylist()
        ]
        rows.sort(key=lambda r: r["entity_id"])
        self.ids = [r["entity_id"] for r in rows]
        self.shapes: list[BaseGeometry] = [
            shapely.from_wkb(r["geometry"]) for r in rows
        ]
        self.tree = shapely.STRtree(self.shapes)

    def locate(self, coordinates: NDArray[np.float64]) -> NDArray[np.int64]:
        points = shapely.points(coordinates[:, 1], coordinates[:, 0])
        pairs = self.tree.query(points, predicate="intersects")
        result = np.full(len(coordinates), len(self.ids), dtype=np.int64)
        if pairs.size:
            np.minimum.at(result, pairs[0], pairs[1])
        result[result == len(self.ids)] = -1
        return result

    def at(self, x: float, y: float) -> BaseGeometry:
        index = int(self.locate(np.array([[y, x]], dtype=np.float64))[0])
        if index < 0:
            raise ValueError("Policy target has no connected GHSL centre")
        return self.shapes[index]

    def anchors(
        self, coordinates: NDArray[np.float64], edge_m: float
    ) -> NDArray[np.int64]:
        """Associate near-edge anchors with a 1 km raster-derived urban centre.

        Source-grid edges and r8 snapping must not let a neighbour own a town's
        core merely because its source point is just outside the raster polygon.
        This changes candidate membership, never the footprint geometry.
        """
        result = self.locate(coordinates)
        for i in np.flatnonzero(result < 0):
            y, x = coordinates[i]
            dy = np.rad2deg(edge_m / 6371008.8)
            dx = dy / max(0.001, np.cos(np.deg2rad(y)))
            candidates = self.tree.query(shapely.box(x - dx, y - dy, x + dx, y + dy))
            nearby = []
            for j in candidates:
                line = shapely.shortest_line(shapely.Point(x, y), self.shapes[j])
                if line is None:
                    raise ValueError("Urban boundary has no shortest line")
                bx, by = line.coords[-1]
                metres = distance(x, y, bx, by)
                if metres <= edge_m:
                    nearby.append((metres, self.ids[j], int(j)))
            if nearby:
                result[i] = min(nearby)[2]
        return result

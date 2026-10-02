"""Select one accepted footprint using stable municipal-before-policy precedence."""

import numpy as np
import shapely
from numpy.typing import NDArray

from build_data.reconcile.common import Row

from .footprints import footprint_order


class BoundaryIndex:
    """Index effective, already subtracted footprints; never extend their limits."""

    def __init__(self, footprints: list[Row]) -> None:
        self.footprints = footprints
        self.tree = shapely.STRtree([r["geometry"] for r in footprints])
        self.order = np.array(
            sorted(
                range(len(footprints)),
                key=lambda i: footprint_order(footprints[i]),
            ),
            dtype=np.int64,
        )
        self.rank = np.argsort(self.order)

    def query(
        self, coordinates: NDArray[np.float64], tolerance: float = 0.0
    ) -> NDArray[np.int64]:
        """Return footprint indices, or -1; tolerance is only for projected water."""
        points = shapely.points(coordinates[:, 1], coordinates[:, 0])
        pairs = self.tree.query(points, predicate="dwithin", distance=tolerance)
        ranks = np.full(len(coordinates), len(self.footprints), dtype=np.int64)
        if pairs.size:
            np.minimum.at(ranks, pairs[0], self.rank[pairs[1]])
        result = np.full(len(coordinates), -1, dtype=np.int64)
        hit = ranks < len(self.footprints)
        result[hit] = self.order[ranks[hit]]
        return result

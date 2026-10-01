"""Complete spherical nearest-neighbour search with stable ID tie breaking."""

import math

import numpy as np
from scipy.spatial import cKDTree

from .errors import DamagedPackError
from .models import Place, PlaceStatus
from .pack import Pack
from .schema import EARTH_RADIUS_KM, TIE_TOLERANCE_KM
from .sphere import distances, unit_vectors


class PlaceLookup:
    def __init__(self, pack: Pack) -> None:
        self.pack = pack
        self._tree: cKDTree | None = None

    def tree(self) -> cKDTree:
        if self._tree is None:
            coordinates = self.pack.arrays["coordinates"]
            xyz = self.pack.arrays["xyz"]
            if not np.isfinite(coordinates).all() or np.any(
                np.abs(coordinates) > [90, 180]
            ):
                raise DamagedPackError("Invalid settlement coordinates")
            if not np.isfinite(xyz).all() or not np.allclose(
                xyz, unit_vectors(coordinates), rtol=0, atol=1e-14
            ):
                raise DamagedPackError("Invalid settlement unit vectors")
            ids = self.pack.arrays["places"]["id"]
            if np.any(ids <= 0) or np.any(ids[1:] <= ids[:-1]):
                raise DamagedPackError(
                    "Settlement IDs must be positive, unique and sorted"
                )
            self._tree = cKDTree(xyz)
        return self._tree

    def lookup(
        self, lat: float, lon: float, cutoff: float | None
    ) -> tuple[Place | None, PlaceStatus]:
        if not len(self.pack.arrays["places"]):
            return None, "no_coverage"
        query = unit_vectors(np.array([lat, lon]))
        tree = self.tree()
        chord, _ = tree.query(query, k=1)
        # Chord radius includes every numerically tied candidate, including antipodes.
        radius = min(2.0, float(chord) + TIE_TOLERANCE_KM / EARTH_RADIUS_KM + 2e-15)
        candidates = np.asarray(
            tree.query_ball_point(query, np.nextafter(radius, math.inf)), dtype=np.int64
        )
        km = distances(query, self.pack.arrays["xyz"][candidates])
        nearest = float(km.min())
        tied = np.flatnonzero(km <= nearest + TIE_TOLERANCE_KM)
        chosen = int(
            tied[np.argmin(self.pack.arrays["places"]["id"][candidates[tied]])]
        )
        index, distance = int(candidates[chosen]), float(km[chosen])
        if cutoff is not None and distance > cutoff:
            return None, "beyond_distance"
        row = self.pack.arrays["places"][index]
        coord = self.pack.arrays["coordinates"][index]
        text = self.pack.text
        return Place(
            int(row["id"]),
            text(int(row["name"])),
            text(int(row["feature"])),
            float(coord[0]),
            float(coord[1]),
            distance,
            text(int(row["country"])) or None,
            text(int(row["admin1"])) or None,
        ), "matched"

    def close(self) -> None:
        self._tree = None

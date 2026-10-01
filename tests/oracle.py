"""Independent haversine oracle reading the documented array layout."""

from pathlib import Path

import numpy as np


class HaversineOracle:
    def __init__(self, path: Path) -> None:
        self.coords = np.load(path / "coordinates.npy", allow_pickle=False)
        self.ids = np.load(path / "places.npy", allow_pickle=False)["id"]

    def nearest(self, lat: float, lon: float) -> tuple[int, float]:
        latitude, longitude = np.deg2rad(self.coords).T
        phi, lam = np.deg2rad([lat, lon])
        a = (
            np.sin((latitude - phi) / 2) ** 2
            + np.cos(phi) * np.cos(latitude) * np.sin((longitude - lam) / 2) ** 2
        )
        km = (
            2
            * 6371.0088
            * np.arctan2(np.sqrt(np.clip(a, 0, 1)), np.sqrt(np.clip(1 - a, 0, 1)))
        )
        tied = np.flatnonzero(km <= km.min() + 1e-9)
        index = int(tied[np.argmin(self.ids[tied])])
        return int(self.ids[index]), float(km[index])

"""Spherical coordinates and stable great-circle distances."""

import numpy as np
from numpy.typing import NDArray

from .schema import EARTH_RADIUS_KM


def unit_vectors(coordinates: NDArray[np.float64]) -> NDArray[np.float64]:
    radians = np.deg2rad(coordinates)
    lat, lon = radians[..., 0], radians[..., 1]
    lon = np.where(coordinates[..., 1] == 180, -np.pi, lon)
    cos_lat = np.where(np.abs(coordinates[..., 0]) == 90, 0.0, np.cos(lat))
    return np.stack(
        (cos_lat * np.cos(lon), cos_lat * np.sin(lon), np.sin(lat)), axis=-1
    )


def distances(
    query: NDArray[np.float64], points: NDArray[np.float64]
) -> NDArray[np.float64]:
    cross = np.linalg.norm(np.cross(points, query), axis=-1)
    dot = np.clip(points @ query, -1.0, 1.0)
    return np.asarray(np.arctan2(cross, dot) * EARTH_RADIUS_KM, dtype=np.float64)

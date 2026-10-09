"""Spherical coordinates and stable great-circle distances."""

import math

import numpy as np
from numpy.typing import NDArray

# The IUGG mean radius, in the units each formula reads.
EARTH_M = 6_371_008.8
EARTH_RADIUS_KM = 6371.0088
BOUNDARY_TOLERANCE_DEG = 1e-9
TIE_TOLERANCE_KM = 1e-9


def distance(x: float, y: float, a: float, b: float) -> float:
    """Haversine metres between (x, y) and (a, b), both longitude first."""
    dy, dx = math.radians(b - y), math.radians(a - x)
    h = (
        math.sin(dy / 2) ** 2
        + math.cos(math.radians(y)) * math.cos(math.radians(b)) * math.sin(dx / 2) ** 2
    )
    return 2 * EARTH_M * math.asin(math.sqrt(min(1.0, h)))


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

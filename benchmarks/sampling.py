"""Seeded original-point workloads; build/test dependencies stay here."""

import numpy as np

from build_data.reference.oracle import FloatArray, Reference
from build_data.reference.schema import EARTH_RADIUS_KM


def sample(reference: Reference, count: int, seed: int, *, nearby: bool) -> FloatArray:
    rng = np.random.default_rng(seed)
    accepted: list[FloatArray] = []
    total = 0
    while total < count:
        size = max(1024, min(10000, 4 * (count - total)))
        if nearby:
            indices = rng.integers(0, len(reference.xyz), size)
            lat, lon = np.deg2rad(reference.pack.arrays["coordinates"][indices]).T
            distance = 5 * np.sqrt(rng.random(size)) / EARTH_RADIUS_KM
            bearing = rng.uniform(0, 2 * np.pi, size)
            target_lat = np.arcsin(
                np.sin(lat) * np.cos(distance)
                + np.cos(lat) * np.sin(distance) * np.cos(bearing)
            )
            target_lon = lon + np.arctan2(
                np.sin(bearing) * np.sin(distance) * np.cos(lat),
                np.cos(distance) - np.sin(lat) * np.sin(target_lat),
            )
            coordinates = np.rad2deg(
                np.column_stack(
                    (target_lat, (target_lon + np.pi) % (2 * np.pi) - np.pi)
                )
            )
        else:
            coordinates = np.column_stack(
                (
                    np.rad2deg(np.arcsin(rng.uniform(-1, 1, size))),
                    rng.uniform(-180, 180, size),
                )
            )
        points = coordinates[reference.admin.membership(coordinates)[2]]
        accepted.append(points)
        total += len(points)
    return np.concatenate(accepted)[:count]

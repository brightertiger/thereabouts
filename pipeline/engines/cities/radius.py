"""Optional population-scaled town footprints, with exact overlap selection."""

import math
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import cKDTree

from pipeline.engines.geo.sphere import EARTH_M, unit_vectors
from pipeline.engines.reconcile.common import Row


def assign(
    coordinates: NDArray[np.float64],
    anchors: NDArray[np.float64],
    populations: NDArray[np.float64],
    identities: NDArray[np.object_],
    settings: Row,
) -> NDArray[np.object_]:
    result = np.full(len(coordinates), None, dtype=object)
    if not len(anchors) or not len(coordinates):
        return cast(NDArray[np.object_], result)
    radii = 1000 * np.clip(
        np.sqrt(
            np.maximum(populations, settings["minimum_population"])
            / (math.pi * settings["density_per_km2"])
        ),
        settings["minimum_km"],
        settings["maximum_km"],
    )
    xyz = unit_vectors(coordinates)
    tree = cKDTree(anchors)
    neighbours = tree.query_ball_point(xyz, 2 * np.sin(max(radii) / (2 * EARTH_M)))
    for i, near in enumerate(neighbours):
        if not near:
            continue
        distances = (
            2
            * EARTH_M
            * np.arcsin(
                np.minimum(1, np.linalg.norm(anchors[near] - xyz[i], axis=1) / 2)
            )
        )
        choices = [
            (d, str(identities[j]))
            for j, d in zip(near, distances, strict=True)
            if d <= radii[j]
        ]
        if choices:
            result[i] = min(choices)[1]
    return cast(NDArray[np.object_], result)

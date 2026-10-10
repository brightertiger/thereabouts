"""Disconnected seam envelopes and their read windows across both seam copies."""

from __future__ import annotations

from pipeline.engines.geo.arrays import FloatArray
from pipeline.engines.geo.windows import windows

Bounds = tuple[float, float, float, float]


def envelopes(coordinates: FloatArray) -> list[Bounds]:
    groups = [coordinates]
    if coordinates[:, 1].max() - coordinates[:, 1].min() > 180:
        groups = [
            coordinates[coordinates[:, 1] < 0],
            coordinates[coordinates[:, 1] >= 0],
        ]
    return [
        (
            float(c[:, 1].min()),
            float(c[:, 0].min()),
            float(c[:, 1].max()),
            float(c[:, 0].max()),
        )
        for c in groups
        if len(c)
    ]


def expanded(bounds: Bounds, offshore_m: float) -> list[Bounds]:
    """The cell reader's windows: a 2% wider reach plus 1e-4 degrees."""
    return windows(bounds, offshore_m, pad=1.02, margin=1e-4, epsilon=1e-8, span=360.0)

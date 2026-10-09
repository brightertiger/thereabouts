"""Longitude-latitude query windows around bounds, including both seam copies."""

import math

from .sphere import EARTH_M

# (west, south, east, north) in; (west, east, south, north) out, as R-trees read.
Bounds = tuple[float, float, float, float]


def windows(
    bounds: Bounds,
    radius_m: float,
    *,
    pad: float = 1.0,
    margin: float = 0.0,
    epsilon: float = 1e-6,
    span: float = 180.0,
) -> list[Bounds]:
    """Windows covering `radius_m * pad` metres plus `margin` degrees around bounds.

    Callers keep their historical tolerances: `pad` and `margin` widen the
    latitude reach, `epsilon` floors the cosine near the poles and `span` caps
    the longitude reach. Shifted copies cover the antimeridian.
    """
    west, south, east, north = bounds
    dy = math.degrees(radius_m * pad / EARTH_M) + margin
    reach = min(90, max(abs(south), abs(north)) + dy)
    dx = min(span, dy / max(epsilon, math.cos(math.radians(reach))))
    bottom, top = max(-90.0, south - dy), min(90.0, north + dy)
    result = []
    for shift in (-360.0, 0.0, 360.0):
        left, right = max(-180.0, west - dx + shift), min(180.0, east + dx + shift)
        if left <= right:
            result.append((left, right, bottom, top))
    return result

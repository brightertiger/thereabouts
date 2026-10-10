"""Shared geometry helpers reproduce each replaced copy bit for bit."""

import itertools
import math
from collections.abc import Iterator

from pipeline.engines.cells.windows import expanded
from pipeline.engines.geo.sphere import EARTH_M, distance
from pipeline.engines.geo.windows import windows

Bounds = tuple[float, float, float, float]

# Verbatim copies of the pre-consolidation helpers (reconcile/spatial.py and
# cells/windows.py at 141cfab), kept here as the byte-identity reference.


def old_haversine(x: float, y: float, a: float, b: float) -> float:
    dy, dx = math.radians(b - y), math.radians(a - x)
    h = (
        math.sin(dy / 2) ** 2
        + math.cos(math.radians(y)) * math.cos(math.radians(b)) * math.sin(dx / 2) ** 2
    )
    return 2 * 6_371_008.8 * math.asin(math.sqrt(min(1.0, h)))


def old_point_windows(x: float, y: float, radius: float) -> Iterator[Bounds]:
    dy = math.degrees(radius / 6_371_008.8)
    dx = min(180.0, dy / max(0.000001, math.cos(math.radians(min(90, abs(y) + dy)))))
    lo, hi = max(-90.0, y - dy), min(90.0, y + dy)
    for shift in (-360.0, 0.0, 360.0):
        left, right = max(-180.0, x - dx + shift), min(180.0, x + dx + shift)
        if left <= right:
            yield left, right, lo, hi


def old_expanded(bounds: Bounds, offshore_m: float) -> list[Bounds]:
    w, s, e, n = bounds
    dy = math.degrees(offshore_m * 1.02 / 6_371_008.8) + 1e-4
    dx = min(
        360.0, dy / max(1e-8, math.cos(math.radians(min(90, max(abs(s), abs(n)) + dy))))
    )
    result = []
    for shift in (-360, 0, 360):
        left, right = max(-180, w - dx + shift), min(180, e + dx + shift)
        if left <= right:
            result.append((left, right, max(-90, s - dy), min(90, n + dy)))
    return result


LONGITUDES = (-180.0, -179.999, -97.25, 0.0, 12.5, 179.9, 180.0)
LATITUDES = (-90.0, -89.99, -45.1, 0.0, 1e-7, 60.0, 89.999, 90.0)
RADII = (0, 1, 900.0, 15_000, 50_000.0, 1_000_000.0)


def test_radius_and_haversine_are_unchanged() -> None:
    assert EARTH_M == 6_371_008.8
    for (x, y), (a, b) in itertools.product(
        itertools.product(LONGITUDES, LATITUDES), repeat=2
    ):
        assert distance(x, y, a, b) == old_haversine(x, y, a, b)


def test_point_windows_match_the_reconcile_copy() -> None:
    for x, y, radius in itertools.product(LONGITUDES, LATITUDES, RADII):
        assert windows((x, y, x, y), radius) == list(old_point_windows(x, y, radius))


def test_cell_windows_match_the_cell_reader_copy() -> None:
    boxes = [
        (w, s, e, n)
        for w, e in itertools.combinations(sorted(LONGITUDES), 2)
        for s, n in itertools.combinations(sorted(LATITUDES), 2)
    ]
    for bounds, radius in itertools.product(boxes, RADII):
        assert expanded(bounds, radius) == old_expanded(bounds, radius)

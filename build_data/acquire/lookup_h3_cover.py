"""Bounded mixed-resolution coverage with resolution-8 center semantics.

H3's geometric parent boundary does NOT contain all logical children. We use
conservative spherical caps based on H3's maximum-edge bounds, doubled (larger
than its 1.4 child-bbox factor), and descend at every uncertain boundary. The
leaf predicate is the center in the original WGS84 polygon, including holes.

Edge constants derived from Uber H3 polyfill.c (Apache-2.0, Copyright 2023 Uber):
https://github.com/uber/h3/blob/v4.3.0/src/h3lib/lib/polyfill.c
No coarse cell is accepted just because its own center/boundary is contained.
"""

from collections import Counter
from collections.abc import Iterator, Sequence
from math import degrees

import h3.api.basic_int as h3i
import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry

MAX_EDGE_RADIANS = (
    0.21577206265130,
    0.08308767068495,
    0.03148970436439,
    0.01190662871439,
    0.00450053330908,
    0.00170105523619,
    0.00064293917678,
    0.00024300820659,
    0.00009184847087,
)
COVER_VERSION = "spherical-cap-2x-max-edge-center-1"


def _walk(
    geometry: BaseGeometry, cells: Sequence[int], level: int, resolution: int
) -> Iterator[int]:
    for start in range(0, len(cells), 4096):
        chunk = cells[start : start + 4096]
        centers = np.array([h3i.cell_to_latlng(cell) for cell in chunk])
        lat, lon = centers[:, 0], centers[:, 1]
        if level == resolution:
            inside = shapely.intersects_xy(geometry, lon, lat)
            yield from (cell for cell, keep in zip(chunk, inside, strict=True) if keep)
            continue
        radius = MAX_EDGE_RADIANS[level] * 2
        north, south = (
            np.minimum(90, lat + degrees(radius)),
            np.maximum(-90, lat - degrees(radius)),
        )
        polar = (north == 90) | (south == -90)
        ratio = np.sin(radius) / np.maximum(1e-15, np.cos(np.radians(lat)))
        half_lon = np.degrees(np.arcsin(np.minimum(1, ratio)))
        west, east = lon - half_lon, lon + half_lon
        west[polar], east[polar] = -180, 180
        boxes = shapely.box(np.maximum(-180, west), south, np.minimum(180, east), north)
        full = shapely.covers(geometry, boxes)
        overlap = shapely.intersects(geometry, boxes)
        # A cap crossing the antimeridian has a second, disjoint planar box.
        for mask, left, right in (
            (west < -180, west + 360, np.full(len(chunk), 180)),
            (east > 180, np.full(len(chunk), -180), east - 360),
        ):
            indices = np.flatnonzero(mask)
            if len(indices):
                other = shapely.box(
                    left[indices], south[indices], right[indices], north[indices]
                )
                full[indices] &= shapely.covers(geometry, other)
                overlap[indices] |= shapely.intersects(geometry, other)
        yield from (cell for cell, keep in zip(chunk, full, strict=True) if keep)
        boundary = [
            cell
            for cell, hit, keep in zip(chunk, overlap, full, strict=True)
            if hit and not keep
        ]
        children = [
            child
            for cell in boundary
            for child in h3i.cell_to_children(cell, level + 1)
        ]
        if children:
            yield from _walk(geometry, children, level + 1, resolution)


def compact(cells: set[int], resolution: int) -> set[int]:
    """Compact nonoverlapping mixed levels without expanding interior cells."""
    for level in range(resolution, 0, -1):
        members = [cell for cell in cells if h3i.get_resolution(cell) == level]
        parents = Counter(h3i.cell_to_parent(cell, level - 1) for cell in members)
        complete = {
            p for p, n in parents.items() if n == (6 if h3i.is_pentagon(p) else 7)
        }
        for parent in complete:
            cells.difference_update(h3i.cell_to_children(parent, level))
        cells.update(complete)
    return cells


def cover(geometry: BaseGeometry, resolution: int = 8) -> list[int]:
    """Return a maximally compact set; poles and longitude wrap are explicit."""
    if not 1 <= resolution <= 8 or not geometry.is_valid or geometry.is_empty:
        raise ValueError("Coverage needs valid nonempty geometry and resolution 1..8")
    shapely.prepare(geometry)
    roots = [
        child
        for cell in h3i.get_res0_cells()
        for child in h3i.cell_to_children(cell, 1)
    ]
    return sorted(compact(set(_walk(geometry, roots, 1, resolution)), resolution))

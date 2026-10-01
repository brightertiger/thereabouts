"""Bounded-memory refinement with exact descendant envelopes and sibling collapse."""

from collections.abc import Iterator

import numpy as np
from h3.api import basic_int as h3
from numpy.typing import NDArray

from pyofflinegeocoder.format import BLOCK_RESOLUTION, H3_DIGIT_BITS, H3_MAX_RESOLUTION
from pyofflinegeocoder.hierarchy import addresses

from .reference.oracle import FloatArray, Labels, Reference
from .reference.schema import BOUNDARY_TOLERANCE_DEG


def blocks(bounds: list[float] | None = None, resolution: int = 8) -> Iterator[int]:
    if bounds is not None:
        w, s, e, n = bounds
        # The source coverage is closed. Move its edges outward for H3's
        # polygon fill, then apply the exact source bounds during labelling.
        w, s = (
            max(-180, w - BOUNDARY_TOLERANCE_DEG),
            max(-90, s - BOUNDARY_TOLERANCE_DEG),
        )
        e, n = min(180, e + BOUNDARY_TOLERANCE_DEG), min(90, n + BOUNDARY_TOLERANCE_DEG)
        polygon = {
            "type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        }
        roots = {
            h3.cell_to_parent(c, BLOCK_RESOLUTION)
            for c in h3.geo_to_cells(polygon, resolution)
        }
        yield from sorted(roots)
        return
    for base in h3.get_res0_cells():
        yield from h3.cell_to_children(base, BLOCK_RESOLUTION)


def descendants(cell: int, resolution: int) -> tuple[NDArray[np.uint64], FloatArray]:
    cells = np.asarray(h3.cell_to_children(cell, resolution), dtype=np.uint64)
    coordinates = np.asarray(
        [h3.cell_to_latlng(int(c)) for c in cells], dtype=np.float64
    )
    return cells, coordinates


def groups(
    cells: NDArray[np.uint64], resolution: int
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    prefixes = cells >> (H3_DIGIT_BITS * (H3_MAX_RESOLUTION - resolution))
    starts = np.r_[0, np.flatnonzero(prefixes[1:] != prefixes[:-1]) + 1].astype(
        np.int64
    )
    return starts, np.diff(np.r_[starts, len(cells)]).astype(np.int64)


def label_block(
    reference: Reference,
    cells: NDArray[np.uint64],
    coordinates: FloatArray,
    resolution: int,
) -> Labels:
    result = np.zeros(len(cells), dtype=np.uint64)
    pending = np.ones(len(cells), dtype=np.bool_)
    for level in range(BLOCK_RESOLUTION, resolution):
        starts, sizes = groups(cells, level)
        active = pending[starts]
        if not active.any():
            return result
        minimum = np.minimum.reduceat(coordinates, starts, axis=0)[active]
        maximum = np.maximum.reduceat(coordinates, starts, axis=0)[active]
        bounds = np.column_stack(
            (minimum[:, 1], minimum[:, 0], maximum[:, 1], maximum[:, 0])
        )
        labels, uniform = reference.certify(bounds)
        values = np.zeros(len(starts), dtype=np.uint64)
        values[active] = labels
        resolved = np.zeros(len(starts), dtype=np.bool_)
        resolved[active] = uniform
        fill = np.repeat(resolved, sizes)
        result[fill] = np.repeat(values, sizes)[fill]
        pending[fill] = False
    if pending.any():
        result[pending] = reference.labels(coordinates[pending])
    return result


def compact(
    cells: NDArray[np.uint64], labels: Labels, resolution: int
) -> tuple[NDArray[np.uint16], Labels]:
    """Keep only maximal uniform subtrees. Zero means no stored ancestor."""
    pending = np.ones(len(cells), dtype=np.bool_)
    keys: list[NDArray[np.uint16]] = []
    values: list[Labels] = []
    for level in range(BLOCK_RESOLUTION, resolution + 1):
        starts, sizes = groups(cells, level)
        low, high = (
            np.minimum.reduceat(labels, starts),
            np.maximum.reduceat(labels, starts),
        )
        uniform = pending[starts] & (low == high)
        chosen = uniform & (low != 0)
        keys.append(addresses(cells[starts[chosen]], level)[1].astype(np.uint16))
        values.append(low[chosen])
        pending[np.repeat(uniform, sizes)] = False
        if not pending.any():
            break
    key, value = np.concatenate(keys), np.concatenate(values)
    order = np.argsort(key)
    return key[order], value[order]

"""One verified, atomic Parquet per resolution-3 subtree, including empty ocean."""

from __future__ import annotations

import numpy as np
from h3.api import basic_int as h3
from numpy.typing import NDArray

from pipeline.engines.hierarchy import groups


def compact(
    cells: NDArray[np.uint64], labels: NDArray[np.uint64]
) -> tuple[NDArray[np.uint64], NDArray[np.uint64]]:
    pending = np.ones(len(cells), dtype=bool)
    stored: list[int] = []
    values: list[np.uint64] = []
    for level in range(3, 9):
        starts, sizes = groups(cells, level)
        low, high = (
            np.minimum.reduceat(labels, starts),
            np.maximum.reduceat(labels, starts),
        )
        uniform = pending[starts] & (low == high)
        chosen = uniform & (low != 0)
        stored.extend(h3.cell_to_parent(int(c), level) for c in cells[starts[chosen]])
        values.extend(low[chosen])
        pending[np.repeat(uniform, sizes)] = False
        if not pending.any():
            break
    return np.array(stored, dtype=np.uint64), np.array(values, dtype=np.uint64)

"""NumPy ancestor searches over one block, without retaining mmap views."""

import numpy as np
from numpy.typing import NDArray

from ..packs.layout import KEYS
from ..packs.spatial import Spatial

# O(d) for depths 0..5 below the r3 block. Finest inputs are always r8.
OFFSETS = (0, 1, 8, 57, 400, 2801)


def search(spatial: Spatial, block: int, keys: list[int]) -> list[int | None]:
    row = spatial.blocks[block]
    stored: NDArray[np.uint16] = np.frombuffer(
        spatial.data,
        dtype="<u2",
        count=row.count,
        offset=spatial.sections[KEYS].offset + row.keys,
    )
    result: NDArray[np.int64] = np.full(len(keys), -1, dtype=np.int64)
    local = np.asarray(keys, dtype=np.int64) - OFFSETS[-1]
    for offset in reversed(OFFSETS):
        target = local + offset
        positions = np.searchsorted(stored, target)
        valid = (result < 0) & (positions < row.count)
        indices = np.flatnonzero(valid)
        hits = indices[stored[positions[indices]] == target[indices]]
        result[hits] = positions[hits]
        local //= 7
    return [None if value < 0 else int(value) for value in result]

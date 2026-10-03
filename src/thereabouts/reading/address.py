"""Vectorized logical addressing of validated resolution-8 H3 inputs."""

import numpy as np
from numpy.typing import NDArray

from ..packs.layout import (
    BLOCK_RESOLUTION,
    CHILD_RADIX,
    H3_BASE_MASK,
    H3_BASE_SHIFT,
    H3_DIGIT_BITS,
    H3_DIGIT_MASK,
    H3_MAX_RESOLUTION,
    H3_RESOLUTION_SHIFT,
    REFERENCE_RESOLUTION,
)

# O(d) for depths 0..5 below the r3 block, as specified in SERVING_FORMAT.md.
OFFSETS = (0, 1, 8, 57, 400, 2801)
RESOLUTION_MASK = np.uint64(~(15 << H3_RESOLUTION_SHIFT) & ((1 << 64) - 1))


def addresses(cells: NDArray[np.uint64]) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    blocks = (cells >> H3_BASE_SHIFT) & H3_BASE_MASK
    local = np.zeros(len(cells), dtype=np.uint64)
    for level in range(1, REFERENCE_RESOLUTION + 1):
        shift = H3_DIGIT_BITS * (H3_MAX_RESOLUTION - level)
        digit = (cells >> shift) & H3_DIGIT_MASK
        if level <= BLOCK_RESOLUTION:
            blocks = blocks * CHILD_RADIX + digit
        else:
            local = local * CHILD_RADIX + digit
    return blocks.astype(np.int64), local.astype(np.int64) + OFFSETS[-1]


def parents(cells: NDArray[np.uint64], keys: NDArray[np.int64]) -> NDArray[np.uint64]:
    resolution = np.searchsorted(OFFSETS, keys, side="right").astype(np.uint64) + 2
    suffix = (np.uint64(1) << ((H3_MAX_RESOLUTION - resolution) * H3_DIGIT_BITS)) - 1
    stored = np.asarray(
        (cells & RESOLUTION_MASK) | (resolution << H3_RESOLUTION_SHIFT) | suffix
    )
    stored[keys < 0] = 0
    return stored

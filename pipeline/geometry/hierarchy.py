"""H3 logical addresses; see docs/DESIGN.md, Mmap format."""

from typing import overload

import numpy as np
from numpy.typing import NDArray

from thereabouts.format import BLOCK_RESOLUTION, H3_DIGIT_BITS, H3_MAX_RESOLUTION

from .format import (
    CHILD_RADIX,
    H3_BASE_MASK,
    H3_BASE_SHIFT,
    H3_DIGIT_MASK,
    Integer,
    level_offset,
)


def _addresses(cells: Integer, resolution: int) -> tuple[Integer, Integer]:
    block = (cells >> H3_BASE_SHIFT) & H3_BASE_MASK
    local = block * 0
    for level in range(1, resolution + 1):
        digit = (cells >> (H3_DIGIT_BITS * (H3_MAX_RESOLUTION - level))) & H3_DIGIT_MASK
        if level <= BLOCK_RESOLUTION:
            block = block * CHILD_RADIX + digit
        else:
            local = local * CHILD_RADIX + digit
    return block, local + level_offset(resolution - BLOCK_RESOLUTION)


@overload
def addresses(cells: int, resolution: int) -> tuple[int, int]: ...


@overload
def addresses(
    cells: NDArray[np.uint64], resolution: int
) -> tuple[NDArray[np.int64], NDArray[np.int64]]: ...


def addresses(
    cells: int | NDArray[np.uint64], resolution: int
) -> tuple[int, int] | tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Use the same digit traversal for a Python integer or a batch of cells."""
    if isinstance(cells, int):
        return _addresses(cells, resolution)
    return _addresses(cells.astype(np.int64), resolution)

"""Sparse key search and dense bitmap rank; see docs/DESIGN.md, Mmap format."""

from bisect import bisect_left
from typing import overload

import numpy as np
from numpy.typing import NDArray

from thereabouts.format import (
    BITMAP_WORD,
    BITMAP_WORD_BITS,
    KEY_BITS,
    KEY_DTYPE,
    KEYS_PER_WORD,
    bitmap_offsets,
)

from .errors import DamagedPackError

IntArray = NDArray[np.int64]


def sparse_positions(
    keys: NDArray[np.uint16], starts: IntArray, counts: IntArray, targets: IntArray
) -> IntArray:
    """Binary-search independent sorted block slices; missing keys return -1."""
    result = np.full(len(targets), -1, dtype=np.int64)
    lo = starts.copy()
    end = lo + counts
    hi = end.copy()
    if np.any(end > len(keys)):
        raise DamagedPackError("invalid sparse key span")
    if len(starts) and np.all(starts == starts[0]) and np.all(counts == counts[0]):
        lo += np.searchsorted(keys[int(lo[0]) : int(hi[0])], targets)
    else:
        while (active := np.flatnonzero(lo < hi)).size:
            mid = (lo[active] + hi[active]) // 2
            less = keys[mid] < targets[active]
            lo[active[less]] = mid[less] + 1
            hi[active[~less]] = mid[~less]
    candidates = np.flatnonzero(lo < end)
    found = candidates[keys[lo[candidates]] == targets[candidates]]
    result[found] = lo[found] - starts[found]
    return result


def bitmap_positions(
    keys: NDArray[np.uint16], starts: IntArray, targets: IntArray, depth: int
) -> IntArray:
    """Test membership and rank set bits before each key; missing keys return -1."""
    offsets, rank_offsets = bitmap_offsets(starts, targets, depth)
    if np.any(rank_offsets >= len(keys)):
        raise DamagedPackError("invalid bitmap span")
    word = np.zeros(len(targets), dtype=np.uint64)
    for digit in range(KEYS_PER_WORD):
        word |= keys[offsets + digit].astype(np.uint64) << np.uint64(KEY_BITS * digit)
    bits = targets.astype(np.uint64) % np.uint64(BITMAP_WORD_BITS)
    return bitmap_rank(word, bits, keys[rank_offsets].astype(np.int64))


@overload
def bitmap_rank(word: int, bit: int, prefix: int) -> int: ...


@overload
def bitmap_rank(
    word: NDArray[np.uint64], bit: NDArray[np.uint64], prefix: IntArray
) -> IntArray: ...


def bitmap_rank(
    word: int | NDArray[np.uint64],
    bit: int | NDArray[np.uint64],
    prefix: int | IntArray,
) -> int | IntArray:
    """One membership/rank formula for scalar words and batches of words."""
    present = ((word >> bit) & 1) != 0
    below = word & ((1 << bit) - 1)
    if isinstance(below, int):
        return int(prefix) + below.bit_count() if present else -1
    return np.where(present, prefix + np.bitwise_count(below).astype(np.int64), -1)


def positions(
    keys: NDArray[np.uint16],
    starts: IntArray,
    counts: IntArray,
    targets: IntArray,
    bitmap: NDArray[np.bool_],
    depth: int,
) -> IntArray:
    result = np.full(len(targets), -1, dtype=np.int64)
    sparse, dense = np.flatnonzero(~bitmap), np.flatnonzero(bitmap)
    if len(sparse):
        result[sparse] = sparse_positions(
            keys, starts[sparse], counts[sparse], targets[sparse]
        )
    if len(dense):
        result[dense] = bitmap_positions(keys, starts[dense], targets[dense], depth)
    return result


def position(
    keys: NDArray[np.uint16],
    start: int,
    count: int,
    target: int,
    bitmap: bool,
    depth: int,
) -> int:
    """Scalar index search using the same bitmap offsets as the batch path."""
    if not bitmap:
        end = start + count
        if end > len(keys):
            raise DamagedPackError("invalid sparse key span")
        found = bisect_left(keys, target, start, end)
        return found - start if found < end and keys[found] == target else -1
    offset, rank_offset = bitmap_offsets(start, target, depth)
    if rank_offset >= len(keys):
        raise DamagedPackError("invalid bitmap span")
    word = BITMAP_WORD.unpack_from(keys.data, offset * KEY_DTYPE.itemsize)[0]
    return bitmap_rank(int(word), target % BITMAP_WORD_BITS, int(keys[rank_offset]))

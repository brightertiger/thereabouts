# cython: language_level=3
"""Reconstruct a stored H3 key; all geographic assignments remain in the data."""

from libc.stdint cimport uint64_t
from h3.api import basic_int as h3

cdef int BLOCK_COUNT = 41846
cdef int MAX_KEY = 19607
cdef int BLOCK_RESOLUTION = 3
cdef int MAX_RESOLUTION = 15
cdef int BASE_SHIFT = 45
cdef int RESOLUTION_SHIFT = 52
cdef uint64_t CELL_MODE = (<uint64_t>1) << 59


def stored_cell(block, key):
    cdef int depth = 0
    cdef int offset = 0
    cdef int next_offset = 1
    cdef int power = 1
    cdef int local, base, i, shift, resolution
    cdef int digits[8]
    cdef uint64_t cell
    if not 0 <= block < BLOCK_COUNT or not 0 <= key <= MAX_KEY:
        raise ValueError("H3 block or local key out of bounds")
    while next_offset <= key:
        depth += 1
        offset = next_offset
        power *= 7
        next_offset += power
    local = key - offset
    base = block
    for i in range(depth):
        digits[i] = local % 7
        local //= 7
    for i in range(depth, depth + BLOCK_RESOLUTION):
        digits[i] = base % 7
        base //= 7
    resolution = BLOCK_RESOLUTION + depth
    cell = (CELL_MODE | ((<uint64_t>resolution) << RESOLUTION_SHIFT)
            | ((<uint64_t>base) << BASE_SHIFT) | (((<uint64_t>1) << BASE_SHIFT) - 1))
    for i in range(resolution):
        shift = 3 * (MAX_RESOLUTION - i - 1)
        cell = (cell & ~((<uint64_t>7) << shift)) | ((<uint64_t>digits[resolution - i - 1]) << shift)
    if not h3.is_valid_cell(cell):
        raise ValueError("Invalid pentagon address")
    return cell

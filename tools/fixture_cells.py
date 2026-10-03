"""Enumerate fixture H3 cells from the documented block/local-key encoding."""

from h3.api import basic_int as h3

BLOCK_RESOLUTION = 3
CHILD_RADIX = 7
BLOCK_COUNT = 122 * CHILD_RADIX**BLOCK_RESOLUTION
MAX_KEY = 19607
H3_DIGIT_BITS = 3
H3_MAX_RESOLUTION = 15
H3_DIGIT_MASK = 7
H3_CELL_MODE = 1 << 59
H3_RESOLUTION_SHIFT = 52
H3_BASE_SHIFT = 45


def level_offset(depth: int) -> int:
    return int((CHILD_RADIX**depth - 1) // (CHILD_RADIX - 1))


def cell_at(block: int, key: int) -> int:
    if not 0 <= block < BLOCK_COUNT or not 0 <= key <= MAX_KEY:
        raise ValueError("H3 block or local key out of bounds")
    depth = 0
    while level_offset(depth + 1) <= key:
        depth += 1
    local = key - level_offset(depth)
    digits = []
    for _ in range(depth):
        digits.append(local % CHILD_RADIX)
        local //= CHILD_RADIX
    for _ in range(BLOCK_RESOLUTION):
        digits.append(block % CHILD_RADIX)
        block //= CHILD_RADIX
    resolution = BLOCK_RESOLUTION + depth
    cell = (
        H3_CELL_MODE
        | (resolution << H3_RESOLUTION_SHIFT)
        | (block << H3_BASE_SHIFT)
        | ((1 << H3_BASE_SHIFT) - 1)
    )
    for level, digit in enumerate(reversed(digits), 1):
        shift = H3_DIGIT_BITS * (H3_MAX_RESOLUTION - level)
        cell = (cell & ~(H3_DIGIT_MASK << shift)) | (digit << shift)
    if not h3.is_valid_cell(cell):
        raise ValueError("Invalid pentagon address")
    return cell

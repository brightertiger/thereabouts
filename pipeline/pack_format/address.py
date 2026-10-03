"""Logical H3 addressing, including unused pentagon digit slots."""

from h3.api import basic_int as h3

from .layout import (
    BLOCK_COUNT,
    BLOCK_RESOLUTION,
    CHILD_RADIX,
    H3_BASE_MASK,
    H3_BASE_SHIFT,
    H3_CELL_MODE,
    H3_DIGIT_BITS,
    H3_DIGIT_MASK,
    H3_MAX_RESOLUTION,
    H3_RESOLUTION_SHIFT,
    MAX_KEY,
)


def level_offset(depth: int) -> int:
    return int((CHILD_RADIX**depth - 1) // (CHILD_RADIX - 1))


def address(cell: int, resolution: int) -> tuple[int, int]:
    block = (cell >> H3_BASE_SHIFT) & H3_BASE_MASK
    local = 0
    for level in range(1, resolution + 1):
        digit = (cell >> (H3_DIGIT_BITS * (H3_MAX_RESOLUTION - level))) & H3_DIGIT_MASK
        if level <= BLOCK_RESOLUTION:
            block = block * CHILD_RADIX + digit
        else:
            local = local * CHILD_RADIX + digit
    return block, level_offset(resolution - BLOCK_RESOLUTION) + local


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


def ancestors(key: int) -> list[int]:
    depth = 0
    while level_offset(depth + 1) <= key:
        depth += 1
    local = key - level_offset(depth)
    result = []
    while depth:
        depth -= 1
        local //= CHILD_RADIX
        result.append(level_offset(depth) + local)
    return result

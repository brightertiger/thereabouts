"""Internal pipeline hierarchy codec; not the public serving-pack format."""

from struct import Struct
from typing import Any, TypeVar

import numpy as np
from numpy.typing import NDArray

from thereabouts.format import BLOCK_RESOLUTION, H3_DIGIT_BITS, H3_MAX_RESOLUTION

H3_BASE_CELLS = 122
H3_DIGIT_MASK = (1 << H3_DIGIT_BITS) - 1
H3_BASE_SHIFT = H3_DIGIT_BITS * H3_MAX_RESOLUTION
H3_BASE_MASK = 127
CHILD_RADIX = 7
BLOCK_COUNT = H3_BASE_CELLS * CHILD_RADIX**BLOCK_RESOLUTION

BYTE_BITS = 8
KEY_DTYPE = np.dtype("<u2")
LABEL_DTYPE = np.dtype("<u8")
VALUE_DTYPES: dict[int, np.dtype[Any]] = {1: np.dtype("u1"), 2: np.dtype("<u2")}
VALUE_WIDTH_MASK = 3
BITMAP_FLAG = 128
BITMAP_WORD_DTYPE = np.dtype("<u8")
BITMAP_WORD = Struct("<Q")
BITMAP_WORD_BITS = BITMAP_WORD_DTYPE.itemsize * BYTE_BITS
KEY_BITS = KEY_DTYPE.itemsize * BYTE_BITS
KEYS_PER_WORD = BITMAP_WORD_DTYPE.itemsize // KEY_DTYPE.itemsize
BITMAP_BYTES_PER_WORD = BITMAP_WORD_DTYPE.itemsize + KEY_DTYPE.itemsize
MAX_DICTIONARY_LABELS = 1 << KEY_BITS

ADMIN_FIELD_BITS = 16
ADMIN_FIELD_MASK = (1 << ADMIN_FIELD_BITS) - 1
CITY_BITS = 32
CITY_MASK = (1 << CITY_BITS) - 1
CITY_CUTOFF_KM = 50.0

DIRECTORY_DTYPE = np.dtype(
    [
        ("keys", "<u4"),
        ("values", "<u4"),
        ("dictionary", "<u4"),
        ("count", "<u4"),
        ("labels", "<u4"),
        ("width", "u1"),
    ]
)

Integer = TypeVar("Integer", int, NDArray[np.int64])


def level_offset(depth: Integer) -> Integer:
    """First local key at this depth below a resolution-3 block."""
    result = (CHILD_RADIX**depth - 1) // (CHILD_RADIX - 1)
    if isinstance(depth, int):
        return int(result)
    return result


def bitmap_word_count(depth: int) -> int:
    return (level_offset(depth + 1) + BITMAP_WORD_BITS - 1) // BITMAP_WORD_BITS


def pack_label(
    country: NDArray[np.int64],
    state: NDArray[np.int64],
    city: NDArray[np.uint64],
    present: NDArray[np.bool_],
) -> NDArray[np.uint64]:
    """Pack zero-based admin rows (-1 missing) and city IDs (0 missing)."""
    admin = 1 + ((country + 1).astype(np.uint64) << ADMIN_FIELD_BITS)
    admin += (state + 1).astype(np.uint64)
    return np.where(present, (admin << CITY_BITS) | city, 0).astype(np.uint64)


def unpack_label(label: int) -> tuple[int, int, int]:
    """Unpack a present label to country/state rows and a city string ID."""
    admin = (label >> CITY_BITS) - 1
    return (
        (admin >> ADMIN_FIELD_BITS) - 1,
        (admin & ADMIN_FIELD_MASK) - 1,
        label & CITY_MASK,
    )


def bitmap_offsets(
    starts: Integer, targets: Integer, depth: int
) -> tuple[Integer, Integer]:
    """Word and prefix-rank offsets, both measured in uint16 keys."""
    word_indices = targets // BITMAP_WORD_BITS
    return (
        starts + KEYS_PER_WORD * word_indices,
        starts + KEYS_PER_WORD * bitmap_word_count(depth) + word_indices,
    )

"""Disk compatibility and scalar/vector agreement at index word boundaries."""

import numpy as np
import pytest

from tests.support.table import encode_keys
from thereabouts.errors import DamagedPackError
from thereabouts.format import BITMAP_FLAG, level_offset, pack_label, unpack_label
from thereabouts.index import position, positions


def test_label_codec_preserves_present_land_and_disk_fields() -> None:
    labels = pack_label(
        np.array([-1, 1, 1], dtype=np.int64),
        np.array([-1, 2, 2], dtype=np.int64),
        np.array([0, 3, 3], dtype=np.uint64),
        np.array([True, True, False]),
    )
    assert labels.tolist() == [0x0000000100000000, 0x0002000400000003, 0]
    assert unpack_label(int(labels[0])) == (-1, -1, 0)
    assert unpack_label(int(labels[1])) == (1, 2, 3)


@pytest.mark.parametrize("count", [300, 2000])
def test_index_search_boundaries_and_missing_keys(count: int) -> None:
    depth = 5
    limit = level_offset(depth + 1)
    stored = np.linspace(0, limit - 1, count, dtype=np.uint16)
    encoded, flag = encode_keys(stored, resolution=8)
    assert bool(flag & BITMAP_FLAG) == (count == 2000)
    targets = np.arange(limit, dtype=np.int64)
    expected = np.full(limit, -1, dtype=np.int64)
    expected[stored] = np.arange(count)
    assert np.array_equal(
        positions(
            encoded,
            np.zeros(limit, dtype=np.int64),
            np.full(limit, count, dtype=np.int64),
            targets,
            np.full(limit, bool(flag), dtype=np.bool_),
            depth,
        ),
        expected,
    )
    assert [
        position(encoded, 0, count, int(k), bool(flag), depth) for k in targets
    ] == expected.tolist()
    with pytest.raises(DamagedPackError):
        position(encoded[:-1], 0, count, limit - 1, bool(flag), depth)

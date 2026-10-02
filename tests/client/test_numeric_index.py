from pathlib import Path
from struct import pack

import numpy as np
import pytest
from h3.api import basic_int as h3

from build_data.serve.encoding import write_container
from thereabouts.packs.address import address
from thereabouts.packs.errors import CorruptPackError
from thereabouts.packs.layout import (
    BLOCKS,
    DIRECTORY,
    KEYS,
    LABEL,
    LABELS,
    SPATIAL,
    VALUES,
)
from thereabouts.packs.spatial import Spatial
from thereabouts.reading.spatial import SpatialIndex


def fixture(path: Path, corrupt: bool = False) -> list[int]:
    blocks = sorted(
        address(h3.latlng_to_cell(a, b, 3), 3)[0]
        for a, b in [(0, 0), (40, 40), (-40, -40)]
    )
    narrow = bytes([255 if corrupt else 0, 0, 0])
    flat = LABEL.pack(1, 0, 0, 8) + LABEL.pack(2, 0, 0, 8)
    wide = pack("<600H", *[i % 300 for i in range(600)])
    dictionary = LABEL.pack(1, 0, 0, 8) + b"".join(
        LABEL.pack(i, 0, 0, 8) for i in range(1, 301)
    )
    rows = [
        (blocks[0], 3, 0, 1, 1, 0, 0),
        (blocks[1], 2, 6, 0, 0, 3, 16),
        (blocks[2], 600, 10, 2, 300, 35, 16),
    ]
    keys = pack("<605H", *[2801, 2802, 2803, 2801, 2802, *range(2801, 3401)])
    write_container(
        path,
        SPATIAL,
        {
            BLOCKS: b"".join(DIRECTORY.pack(*row) for row in rows),
            KEYS: keys,
            VALUES: narrow + flat + wide,
            LABELS: dictionary,
        },
    )
    return blocks


def test_mixed_encodings_unaligned_values_and_all_ancestor_misses(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cells.bin"
    blocks = fixture(path)
    shard = Spatial(path, 300)
    index = SpatialIndex(shard)
    try:
        queries = [
            (block, key) for block in blocks for key in (2801, 2802, 3100, 3400, 19607)
        ]
        numeric_blocks, numeric_keys = np.array(queries, dtype=np.int64).T
        stored, labels = index.lookup_many(numeric_blocks, numeric_keys)
        for i, (block, key) in enumerate(queries):
            expected = shard.lookup(block, key)
            actual = (
                None if stored[i] < 0 else (int(stored[i]), tuple(map(int, labels[i])))
            )
            assert actual == expected == index.lookup(block, key)
    finally:
        index.close()
        shard.close()


def test_bad_selectors_fail_before_query_and_release_views(tmp_path: Path) -> None:
    path = tmp_path / "cells.bin"
    fixture(path, corrupt=True)
    shard = Spatial(path, 300)
    try:
        with pytest.raises(CorruptPackError, match="selector"):
            SpatialIndex(shard)
    finally:
        shard.close()

"""Full offline verification; opening the runtime table never scans every row."""

from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from pipeline.runtime.jsonio import sha256_file as sha256
from thereabouts.errors import DamagedPackError
from thereabouts.format import (
    BITMAP_FLAG,
    BLOCK_RESOLUTION,
    CHILD_RADIX,
    VALUE_DTYPES,
    VALUE_WIDTH_MASK,
    level_offset,
)
from thereabouts.index import positions
from thereabouts.table import Layer, Table


def block_keys(layer: Layer, row: np.void, depth: int) -> NDArray[np.int64]:
    """Validate key spans and recover sorted local keys from either encoding."""
    count = int(row["count"])
    limit = level_offset(depth + 1)
    width = int(row["width"]) & VALUE_WIDTH_MASK
    if width not in (1, 2) or int(row["width"]) not in (
        1,
        2,
        1 | BITMAP_FLAG,
        2 | BITMAP_FLAG,
    ):
        raise ValueError("invalid value width")
    start = int(row["keys"])
    if row["width"] & BITMAP_FLAG:
        targets = np.arange(limit, dtype=np.int64)
        found = positions(
            layer.keys,
            np.full(limit, start, dtype=np.int64),
            np.full(limit, count, dtype=np.int64),
            targets,
            np.ones(limit, dtype=np.bool_),
            depth,
        )
        if not np.array_equal(found[found >= 0], np.arange(count)):
            raise ValueError("invalid bitmap ranks")
        keys = targets[found >= 0]
    else:
        keys = layer.keys[start : start + count].astype(np.int64)
        if len(keys) != count or np.any(keys[1:] <= keys[:-1]) or keys[-1] >= limit:
            raise ValueError("invalid sorted hierarchy keys")
    return keys


def verify_disjoint(keys: NDArray[np.int64], depth: int) -> None:
    """A stored key must have no other stored key in its ancestor chain."""
    # Stored cells are disjoint: a key cannot have a stored ancestor.
    present = set(map(int, keys))
    for level in range(1, depth + 1):
        offset = level_offset(level)
        at_level = keys[(keys >= offset) & (keys < level_offset(level + 1))]
        for ancestor in range(level):
            parents = (at_level - offset) // (
                CHILD_RADIX ** (level - ancestor)
            ) + level_offset(ancestor)
            if any(int(k) in present for k in parents):
                raise ValueError("overlapping ancestor rows")


def verify_values(table: Table, row: np.void) -> None:
    """Check each local dictionary reference and its decoded public label."""
    layer = table.layer
    count = int(row["count"])
    width = int(row["width"]) & VALUE_WIDTH_MASK
    value_start = int(row["values"])
    raw = layer.values[value_start : value_start + count * width]
    if len(raw) != count * width:
        raise ValueError("invalid value span")
    ids = raw.view(VALUE_DTYPES[width])
    if ids.max() >= row["labels"] or int(row["dictionary"]) + int(row["labels"]) > len(
        layer.dictionary
    ):
        raise ValueError("invalid dictionary span")
    for label in layer.dictionary[
        int(row["dictionary"]) : int(row["dictionary"]) + int(row["labels"])
    ]:
        if not label:
            raise ValueError("zero labels must be omitted")
        table.location(int(label))


def verify(path: Path) -> None:
    table = Table(path)
    try:
        for name, entry in table.manifest["files"].items():
            if "/" in name or "\\" in name or name in (".", ".."):
                raise ValueError("invalid file name")
            if sha256(path / name) != entry["sha256"]:
                raise ValueError(f"checksum mismatch: {name}")
        depth = table.resolution - BLOCK_RESOLUTION
        layer = table.layer
        for row in layer.directory:
            count = int(row["count"])
            if not count:
                continue
            keys = block_keys(layer, row, depth)
            verify_disjoint(keys, depth)
            verify_values(table, row)
        offsets = table.city_offsets
        if (
            len(offsets) < 2
            or offsets[0] != 0
            or offsets[-1] != len(table.city_text)
            or np.any(offsets[1:] < offsets[:-1])
        ):
            raise ValueError("invalid city offsets")
        table.city_text.tobytes().decode("utf-8")
    except (ValueError, OSError, IndexError) as exc:
        raise DamagedPackError(f"Verification failed: {exc}") from exc
    finally:
        table.close()

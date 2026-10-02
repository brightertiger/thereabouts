"""Mapped numeric indexes, validated once when a shard is first used."""

from bisect import bisect_left
from typing import cast

import numpy as np
from numpy.typing import NDArray

from ..packs.errors import CorruptPackError
from ..packs.layout import (
    CHILD_RADIX,
    CITY_METHOD_MASK,
    COUNTRY_AREA,
    KEYS,
    LABEL,
    LABEL_FLAGS_MASK,
    LABELS,
    MAX_KEY,
    STATE_AREA,
    U16,
    VALUES,
)
from ..packs.spatial import Label, Spatial
from .address import OFFSETS

IntegerArray = NDArray[np.int64]
LabelArray = NDArray[np.uint32]


class SpatialIndex:
    def __init__(self, shard: Spatial) -> None:
        self.shard = shard
        self.keys: NDArray[np.uint16] = np.frombuffer(
            shard.data,
            dtype="<u2",
            offset=shard.sections[KEYS].offset,
            count=shard.sections[KEYS].count,
        )
        self.bytes: NDArray[np.uint8] = np.frombuffer(shard.data, dtype="u1")
        self.ids = np.array(shard.ids, dtype=np.int64)
        self.rows = np.array(
            [
                (
                    r.keys // U16.size,
                    r.count,
                    r.width,
                    r.values + shard.sections[VALUES].offset,
                    r.dictionary + shard.sections[LABELS].offset,
                    r.labels,
                )
                for r in shard.blocks.values()
            ],
            dtype=np.int64,
        )
        self.block_keys = {
            b: self.keys[r.keys // U16.size : r.keys // U16.size + r.count]
            for b, r in shard.blocks.items()
        }
        error = self._validate()
        if error is not None:
            self.close()
            raise CorruptPackError(error)

    def _validate(self) -> str | None:
        for start, count, width, values, dictionary, labels in self.rows:
            keys = self.keys[start : start + count]
            if np.any(keys > MAX_KEY) or np.any(keys[1:] <= keys[:-1]):
                return "Invalid or unsorted local keys"
            if width:
                selectors = self.bytes[values : values + count * width : width].astype(
                    np.uint16
                )
                if width == 2:
                    selectors |= (
                        self.bytes[values + 1 : values + count * width : width].astype(
                            np.uint16
                        )
                        << 8
                    )
                if np.any(selectors >= labels):
                    return "Dangling dictionary selector"
                offset, size = dictionary, labels
            else:
                offset, size = values, count
            entries = np.frombuffer(
                self.shard.data, dtype="<u4", offset=int(offset), count=int(size * 4)
            ).reshape(-1, 4)
            refs, flags = entries[:, :3], entries[:, 3]
            if (
                np.any(refs > self.shard.places)
                or np.any(flags > LABEL_FLAGS_MASK)
                or np.any((refs[:, 0] != 0) != ((flags & COUNTRY_AREA) != 0))
                or np.any((refs[:, 1] != 0) != ((flags & STATE_AREA) != 0))
                or np.any((refs[:, 2] != 0) != ((flags & CITY_METHOD_MASK) != 0))
            ):
                return "Invalid label references, flags or method nulls"

        return None

    def lookup(self, block: int, key: int) -> tuple[int, Label] | None:
        keys = self.block_keys[block]
        row = self.shard.blocks[block]
        local = key - OFFSETS[-1]
        for offset in reversed(OFFSETS):
            target = local + offset
            position = bisect_left(keys, target)
            if position < row.count and keys[position] == target:
                value = self.shard.sections[VALUES].offset + row.values
                if row.width:
                    value += position * row.width
                    selector = int.from_bytes(
                        self.shard.data[value : value + row.width], "little"
                    )
                    value = (
                        self.shard.sections[LABELS].offset
                        + row.dictionary
                        + selector * LABEL.size
                    )
                else:
                    value += position * LABEL.size
                return target, cast(Label, LABEL.unpack_from(self.shard.data, value))
            local //= CHILD_RADIX
        return None

    def lookup_many(
        self, blocks: IntegerArray, keys: IntegerArray
    ) -> tuple[IntegerArray, LabelArray]:
        rows = self.rows[np.searchsorted(self.ids, blocks)]
        starts, counts = rows[:, 0], rows[:, 1]
        positions = np.full(len(keys), -1, dtype=np.int64)
        stored = np.full(len(keys), -1, dtype=np.int64)
        local = keys - OFFSETS[-1]
        for offset in reversed(OFFSETS):
            pending = np.flatnonzero((positions < 0) & (counts > 0))
            if not len(pending):
                break
            targets = local[pending] + offset
            lo, hi = starts[pending].copy(), (starts + counts)[pending]
            # Parallel binary searches have independent bounds in the flattened shard.
            while np.any(lo < hi):
                mid = (lo + hi) // 2
                active = lo < hi
                safe = np.minimum(mid, len(self.keys) - 1)
                less = self.keys[safe] < targets
                lo = np.where(active & less, mid + 1, lo)
                hi = np.where(active & ~less, mid, hi)
            inside = lo < (starts + counts)[pending]
            matched = inside & (
                self.keys[np.minimum(lo, len(self.keys) - 1)] == targets
            )
            hit = pending[matched]
            positions[hit] = lo[matched] - starts[hit]
            stored[hit] = targets[matched]
            local //= CHILD_RADIX
        labels = np.zeros((len(keys), 4), dtype=np.uint32)
        hit = np.flatnonzero(positions >= 0)
        if len(hit):
            labels[hit] = self._labels(rows[hit], positions[hit])
        return stored, labels

    def _labels(self, rows: IntegerArray, positions: IntegerArray) -> LabelArray:
        widths = rows[:, 2]
        offsets = rows[:, 3] + positions * np.where(widths > 0, widths, LABEL.size)
        dictionary = widths > 0
        # Flat rows are already at the label's first word.
        chosen = np.flatnonzero(dictionary)
        if len(chosen):
            at, width = offsets[chosen], widths[chosen]
            selectors = self.bytes[at].astype(np.int64)
            selectors |= (self.bytes[at + width - 1].astype(np.int64) << 8) * (
                width - 1
            )
            offsets[chosen] = rows[chosen, 4] + selectors * LABEL.size
        return cast(
            LabelArray,
            self.bytes[offsets[:, None] + np.arange(LABEL.size)]
            .view("<u4")
            .reshape(-1, 4),
        )

    def close(self) -> None:
        self.block_keys.clear()
        del self.keys, self.bytes

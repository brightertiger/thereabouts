"""Decode one spatial shard; full validation checks logical cell disjointness."""

from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .address import ancestors, cell_at
from .container import Container
from .errors import CorruptPackError
from .layout import (
    BLOCKS,
    DIRECTORY,
    KEYS,
    LABEL,
    LABELS,
    MAX_BLOCK_ROWS,
    SPATIAL,
    U16,
    VALUES,
    check_label,
)

Label = tuple[int, int, int, int]


@dataclass(frozen=True)
class Block:
    block: int
    count: int
    keys: int
    width: int
    labels: int
    values: int
    dictionary: int


class Spatial(Container):
    def __init__(self, path: Path, places: int) -> None:
        super().__init__(path, SPATIAL)
        self.places = places
        try:
            self.blocks = self._blocks()
            self.ids = tuple(self.blocks)
        except (ValueError, CorruptPackError):
            self.close()
            raise

    def _blocks(self) -> dict[int, Block]:
        span = self.sections[BLOCKS]
        result: dict[int, Block] = {}
        keys_end = values_end = labels_end = 0
        for offset in range(span.offset, span.offset + span.size, DIRECTORY.size):
            row = Block(*DIRECTORY.unpack_from(self.data, offset))
            cell_at(row.block, 0)
            if result and row.block <= next(reversed(result)):
                raise CorruptPackError("Unsorted block directory")
            if row.count > MAX_BLOCK_ROWS or row.width not in (0, 1, 2):
                raise CorruptPackError("Invalid block count or encoding")
            if row.width == 0 and row.labels != 0:
                raise CorruptPackError("Flat labels cannot have a dictionary")
            if row.width and not 0 < row.labels <= min(row.count, 2 ** (8 * row.width)):
                raise CorruptPackError("Invalid dictionary size")
            if (row.keys, row.values, row.dictionary) != (
                keys_end,
                values_end,
                labels_end,
            ):
                raise CorruptPackError("Noncontiguous block spans")
            keys_end += row.count * U16.size
            values_end += row.count * (row.width or LABEL.size)
            labels_end += row.labels * LABEL.size
            result[row.block] = row
        for section, size in (
            (KEYS, keys_end),
            (VALUES, values_end),
            (LABELS, labels_end),
        ):
            if size != self.sections[section].size:
                raise CorruptPackError("Block spans exceed section bounds")
        if not result:
            raise CorruptPackError("Empty spatial directory")
        return result

    def keys(self, row: Block) -> tuple[int, ...]:
        start = self.sections[KEYS].offset + row.keys
        return tuple(
            v[0] for v in U16.iter_unpack(self.data[start : start + 2 * row.count])
        )

    def label(self, row: Block, position: int) -> Label:
        if not 0 <= position < row.count:
            raise CorruptPackError("Invalid row index")
        offset = self.sections[VALUES].offset + row.values
        if row.width:
            selector = int.from_bytes(
                self.data[
                    offset + position * row.width : offset + (position + 1) * row.width
                ],
                "little",
            )
            if selector >= row.labels:
                raise CorruptPackError("Dangling dictionary selector")
            offset = (
                self.sections[LABELS].offset + row.dictionary + selector * LABEL.size
            )
        else:
            offset += position * LABEL.size
        label = cast(Label, LABEL.unpack_from(self.data, offset))
        try:
            check_label(label, self.places)
        except ValueError as exc:
            raise CorruptPackError(str(exc)) from exc
        return label

    def lookup(self, block: int, key: int) -> tuple[int, Label] | None:
        row = self.blocks[block]
        start = self.sections[KEYS].offset + row.keys
        for target in [key, *ancestors(key)]:
            lo, hi = 0, row.count
            while lo < hi:
                mid = (lo + hi) // 2
                value = U16.unpack_from(self.data, start + mid * 2)[0]
                if value < target:
                    lo = mid + 1
                else:
                    hi = mid
            if (
                lo < row.count
                and U16.unpack_from(self.data, start + lo * 2)[0] == target
            ):
                return target, self.label(row, lo)
        return None

    def verify(self) -> None:
        for row in self.blocks.values():
            keys = self.keys(row)
            previous = -1
            for i, key in enumerate(keys):
                cell_at(row.block, key)
                if key <= previous:
                    raise CorruptPackError("Duplicate or unsorted local keys")
                for ancestor in ancestors(key):
                    j = bisect_left(keys, ancestor)
                    if j < len(keys) and keys[j] == ancestor:
                        raise CorruptPackError("Overlapping stored ancestors")
                self.label(row, i)
                previous = key
            if row.width:
                start = self.sections[LABELS].offset + row.dictionary
                labels = [
                    LABEL.unpack_from(self.data, start + i * LABEL.size)
                    for i in range(row.labels)
                ]
                if labels != sorted(set(labels)):
                    raise CorruptPackError("Dictionary must be unique and sorted")
                for label in labels:
                    check_label(cast(Label, label), self.places)

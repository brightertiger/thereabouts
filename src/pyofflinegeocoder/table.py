"""Memory-mapped H3 hierarchy with local keys and per-block dictionaries."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast, overload

import numpy as np
from numpy.typing import NDArray

from .errors import DamagedPackError
from .format import (
    BITMAP_FLAG,
    BLOCK_COUNT,
    BLOCK_RESOLUTION,
    BYTE_BITS,
    CHILD_RADIX,
    DIRECTORY_DTYPE,
    KEY_DTYPE,
    LABEL_DTYPE,
    VALUE_WIDTH_MASK,
    level_offset,
    unpack_label,
)
from .hierarchy import addresses
from .index import position, positions
from .manifest import read_manifest
from .models import Location

Array = NDArray[Any]


class Layer:
    def __init__(self, table: "Table") -> None:
        name = "combined"
        self.directory = table.array(f"{name}-directory.npy", DIRECTORY_DTYPE)
        if self.directory.shape != (BLOCK_COUNT,):
            raise ValueError("invalid block directory")
        self.keys = np.asarray(table.array(f"{name}-keys.bin", KEY_DTYPE))
        self.values = np.asarray(table.array(f"{name}-values.bin", np.dtype("u1")))
        self.dictionary = np.asarray(table.array(f"{name}-dictionary.bin", LABEL_DTYPE))

    def lookup(
        self, blocks: NDArray[np.int64], local: NDArray[np.int64], depth: int
    ) -> NDArray[np.uint64]:
        result = np.zeros(len(blocks), dtype=np.uint64)
        pending = np.flatnonzero(self.directory[blocks]["count"] > 0)
        if not len(pending):
            return result
        rows = self.directory[blocks[pending]]
        found = self._ancestor_positions(rows, local[pending], depth)
        matched = np.flatnonzero(np.any(found >= 0, axis=1))
        chosen = found[matched, np.argmax(found[matched] >= 0, axis=1)]
        result[pending[matched]] = self._decode(rows[matched], chosen)
        return result

    def _ancestor_positions(
        self, rows: Array, local: NDArray[np.int64], depth: int
    ) -> NDArray[np.int64]:
        """Expand finest-to-coarsest logical keys and search each block index."""
        levels = np.arange(depth, -1, -1, dtype=np.int64)
        targets = local[:, None] // (CHILD_RADIX ** (depth - levels)) + level_offset(
            levels
        )
        starts = np.repeat(rows["keys"].astype(np.int64), depth + 1)
        counts = np.repeat(rows["count"].astype(np.int64), depth + 1)
        bitmap = np.repeat((rows["width"] & BITMAP_FLAG) != 0, depth + 1)
        return positions(
            self.keys, starts, counts, targets.ravel(), bitmap, depth
        ).reshape(-1, depth + 1)

    @overload
    def _decode(self, rows: np.void, positions: int) -> int: ...

    @overload
    def _decode(
        self, rows: Array, positions: NDArray[np.int64]
    ) -> NDArray[np.uint64]: ...

    def _decode(
        self, rows: Array | np.void, positions: int | NDArray[np.int64]
    ) -> int | NDArray[np.uint64]:
        """Validate spans and decode local IDs for either one row or a batch."""
        widths = (rows["width"] & VALUE_WIDTH_MASK).astype(np.int64)
        offsets = rows["values"].astype(np.int64) + positions * widths
        if invalid(
            (widths < 1)
            | (widths > 2)
            | (offsets + widths > len(self.values))
            | (positions >= rows["count"])
        ):
            raise DamagedPackError("invalid value span")
        # For narrow values the high-byte contribution is zero. Re-reading the
        # same byte keeps this elementwise decoder identical for scalars/batches.
        ids = self.values[offsets].astype(np.int64)
        ids |= (self.values[offsets + widths - 1].astype(np.int64) << BYTE_BITS) * (
            widths - 1
        )
        entries = rows["dictionary"].astype(np.int64) + ids
        if invalid((ids >= rows["labels"]) | (entries >= len(self.dictionary))):
            raise DamagedPackError("invalid dictionary reference")
        labels = self.dictionary[entries]
        return (
            int(labels)
            if isinstance(positions, int)
            else cast(NDArray[np.uint64], labels)
        )

    def lookup_one(self, block: int, local: int, depth: int) -> int:
        """Search a single logical ancestor chain without allocating a batch."""
        row = self.directory[block]
        count = int(row["count"])
        if not count:
            return 0
        start = int(row["keys"])
        bitmap = bool(row["width"] & BITMAP_FLAG)
        for level in range(depth, -1, -1):
            found = position(
                self.keys, start, count, local + level_offset(level), bitmap, depth
            )
            if found >= 0:
                return self._decode(row, found)
            local //= CHILD_RADIX
        return 0


def invalid(condition: np.bool_ | NDArray[np.bool_]) -> bool:
    """Reduce a validation predicate without NumPy dispatch for scalar rows."""
    return (
        bool(condition.any()) if isinstance(condition, np.ndarray) else bool(condition)
    )


class Table:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.arrays: list[Array] = []
        self.manifest = read_manifest(path)
        self.resolution = int(self.manifest["resolution"])
        try:
            self._check_file("catalog.json")
            if (path / "catalog.json").stat().st_size > 2_000_000:
                raise ValueError("catalog metadata too large")
            self.catalog = json.loads(
                (path / "catalog.json").read_text(encoding="utf-8")
            )
            self.city_offsets = self.array("city-offsets.bin", np.dtype("<u4"))
            self.city_text = self.array("city-text.bin", np.dtype("u1"))
            self.layer = Layer(self)
            self.location = lru_cache(maxsize=8192)(self._location)
        except (OSError, ValueError, TypeError, KeyError, EOFError) as exc:
            self.close()
            raise DamagedPackError(f"Invalid table: {exc}") from exc

    def _check_file(self, name: str) -> None:
        expected = self.manifest["files"][name]["size"]
        if (self.path / name).stat().st_size != expected:
            raise ValueError(f"incorrect file size: {name}")

    def array(self, name: str, dtype: np.dtype[Any]) -> Array:
        self._check_file(name)
        file = self.path / name
        if name.endswith(".npy"):
            result = np.load(file, mmap_mode="r", allow_pickle=False)
            if not isinstance(result, np.memmap):
                closer = getattr(result, "close", None)
                if closer is not None:
                    closer()
                raise ValueError(f"expected an NPY array: {name}")
            self.arrays.append(result)
            if (
                result.dtype != dtype
                or result.ndim != 1
                or result.offset + result.nbytes != file.stat().st_size
            ):
                raise ValueError(f"invalid array: {name}")
            return result
        elif file.stat().st_size == 0:
            result = np.empty(0, dtype=dtype)
        else:
            result = np.memmap(file, mode="r", dtype=dtype)
        self.arrays.append(result)
        return cast(Array, result)

    def labels(self, cells: NDArray[np.uint64]) -> NDArray[np.uint64]:
        blocks, keys = addresses(cells, self.resolution)
        depth = self.resolution - BLOCK_RESOLUTION
        local = keys - level_offset(depth)
        return self.layer.lookup(blocks, local, depth)

    def lookup_one(self, cell: int) -> Location | None:
        block, key = addresses(cell, self.resolution)
        depth = self.resolution - BLOCK_RESOLUTION
        label = self.layer.lookup_one(block, key - level_offset(depth), depth)
        return self.location(label)

    def lookup(self, cells: NDArray[np.uint64]) -> list[Location | None]:
        return [self.location(int(label)) for label in self.labels(cells)]

    def _location(self, label: int) -> Location | None:
        if label == 0:
            return None
        country, state, city = unpack_label(label)
        try:
            name, code = (
                self.catalog["countries"][country] if country >= 0 else (None, None)
            )
            subdivision = self.catalog["states"][state] if state >= 0 else None
            city_name = None
            if city:
                start, stop = self.city_offsets[city : city + 2]
                if not 0 <= start <= stop <= len(self.city_text):
                    raise ValueError("invalid city text span")
                city_name = self.city_text[start:stop].tobytes().decode("utf-8")
            return Location(city_name, subdivision, name, code)
        except (IndexError, ValueError, TypeError) as exc:
            raise DamagedPackError(f"Invalid location reference: {exc}") from exc

    def close(self) -> None:
        if hasattr(self, "location"):
            self.location.cache_clear()
        for array in self.arrays:
            mapping = getattr(array, "_mmap", None)
            if mapping is not None:
                mapping.close()
        self.arrays.clear()

"""Batch ancestor reads and comparable city measures at original r8 centres."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from functools import partial
from pathlib import Path

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from numpy.typing import NDArray

from pipeline.engines.cache import Cache
from pipeline.engines.cells.reader import Cells
from pipeline.engines.reconcile.common import Row

from .engine import Engine


def column_block(path: Path) -> tuple[pa.Table, NDArray[np.uint64], NDArray[np.uint64]]:
    table = pq.read_table(path)
    keys = table["h3_uint64"].to_numpy().astype(np.uint64)
    resolution = table["h3_resolution"].to_numpy().astype(np.uint64)
    mask = (np.uint64(1) << (3 * (15 - resolution))) - np.uint64(1)
    base = (keys & np.uint64(((1 << 64) - 1) ^ (15 << 52))) | np.uint64(8 << 52)
    low, high = (base & ~mask) | np.uint64((1 << 21) - 1), base | mask
    order = np.argsort(low)
    return table.take(pa.array(order, type=pa.int64())), low[order], high[order]


ColumnBlock = tuple[pa.Table, NDArray[np.uint64], NDArray[np.uint64]]
_columns: Cache[tuple[Path, int, int], ColumnBlock] = Cache()


def lookup(reader: Cells, cells: list[str]) -> list[Row]:
    groups: dict[str, list[int]] = {}
    for i, cell in enumerate(cells):
        groups.setdefault(h3.cell_to_parent(cell, 3), []).append(i)
    result: list[Row] = [{} for _ in cells]
    for root, indices in groups.items():
        if root not in reader.blocks:
            for i in indices:
                result[i] = {"cell_status": "pending"}
            continue
        path = reader.blocks[root]
        stamp = path.stat()
        table, low, high = _columns.get(
            (path, stamp.st_size, stamp.st_mtime_ns),
            partial(column_block, path),
            reader.limits.column_cache_entries,
        )
        keys = np.array([int(cells[i], 16) for i in indices], dtype=np.uint64)
        chosen = np.searchsorted(low, keys, side="right") - 1
        valid = chosen >= 0
        if len(high):
            valid &= keys <= high[np.maximum(chosen, 0)]
        records = iter(table.take(pa.array(chosen[valid], type=pa.int64())).to_pylist())
        for i, hit in zip(indices, valid, strict=True):
            result[i] = (
                {**next(records), "cell_status": "matched"}
                if hit
                else {"cell_status": "ineligible"}
            )
    return result


class Comparison:
    def __init__(
        self,
        before: Cells,
        engines: Mapping[str, Engine],
        radius: bool,
        after: Cells | None = None,
    ) -> None:
        self.before, self.after = before, after
        self.engines, self.radius = engines, radius

    def query(self, cells: list[str]) -> tuple[list[Row], list[Row]]:
        before = lookup(self.before, cells)
        if self.after is not None:
            return before, lookup(self.after, cells)
        after = [dict(r) for r in before]
        coordinates: NDArray[np.float64] = np.array(
            [h3.cell_to_latlng(c) for c in cells], dtype=np.float64
        ).reshape((-1, 2))
        for cc in self.engines:
            chosen = np.array(
                [
                    i
                    for i, r in enumerate(before)
                    if r.get("country_id") == f"country:{cc}"
                ],
                dtype=np.int64,
            )
            if not len(chosen):
                continue
            engine = self.engines[cc]
            ids, methods = engine.apply(
                coordinates[chosen],
                np.array([before[i].get("city_id") for i in chosen], dtype=object),
                np.array([before[i].get("city_method") for i in chosen], dtype=object),
                self.radius,
                np.array([before[i].get("land_method") == "offshore" for i in chosen]),
            )
            for i, identity, method in zip(chosen, ids, methods, strict=True):
                after[i].update(city_id=identity, city_method=method)
        return before, after


def measure(rows: list[Row], target: str | None = None) -> Row:
    eligible = [r for r in rows if r.get("cell_status") == "matched"]
    counts = Counter(r.get("city_id") for r in eligible)
    expected = counts[target] if target else None
    return {
        "eligible": len(eligible),
        "distinct_answers": len(counts),
        "expected": expected,
        "share": expected / len(eligible)
        if expected is not None and eligible
        else None,
        "answers": {str(k): v for k, v in counts.most_common()},
    }

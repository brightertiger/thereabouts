"""Resolve the original resolution-8 key through exactly one stored ancestor."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Protocol

import h3
import pyarrow.parquet as pq

from pipeline.config.engines import EngineLimits
from pipeline.engines.reconcile.common import Row


class Reader(Protocol):
    def lookup(self, cell: str | None) -> Row: ...


class Cells:
    def __init__(self, tables: list[Row], limits: EngineLimits | None = None) -> None:
        self.limits = limits or EngineLimits()
        self.blocks = {
            r["block"]: Path(r["path"]) for r in tables if r["kind"] == "cells"
        }
        self.cache: OrderedDict[str, dict[str, Row]] = OrderedDict()

    def block(self, root: str) -> dict[str, Row]:
        if root in self.cache:
            self.cache.move_to_end(root)
            return self.cache[root]
        with pq.ParquetFile(self.blocks[root]) as file:
            value = {r["h3"]: r for r in file.read().to_pylist()}
        if len(self.cache) >= self.limits.reader_cache_entries:
            self.cache.popitem(last=False)
        self.cache[root] = value
        return value

    def lookup(self, cell: str | None) -> Row:
        if cell is None:
            return {"cell_status": "unlocated"}
        if not h3.is_valid_cell(cell) or h3.get_resolution(cell) != 8:
            raise ValueError("Golden lookup requires a resolution-8 H3 cell")
        root = h3.cell_to_parent(cell, 3)
        if root not in self.blocks:
            return {"cell_status": "pending"}
        block = self.block(root)
        for resolution in range(8, 2, -1):
            parent = h3.cell_to_parent(cell, resolution)
            if parent in block:
                row = block[parent]
                return {
                    **row,
                    "cell_status": "matched" if row["country_id"] else "unassigned",
                }
        return {"cell_status": "ineligible"}


def interval(cell: int, resolution: int) -> tuple[int, int]:
    """Inclusive integer range containing exactly the valid r8 descendants.

    Invalid H3 digit strings in the gaps are harmless: all lookup keys are valid.
    All seven unused digits in an r8 key are fixed to 7. Pentagon deleted digits
    create gaps, never valid descendants of another parent.
    """
    mask = (1 << (3 * (15 - resolution))) - 1
    base = (cell & ~(15 << 52) & ~mask) | (8 << 52)
    return base | ((1 << 21) - 1), base | mask

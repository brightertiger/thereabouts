"""Bound cell row groups by H3 blocks and verify their manifest index."""

from pathlib import PurePosixPath
from typing import cast

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from h3.api import basic_int as h3

from pipeline.config.schema import H3

from .selection import Selection
from .source import Row

# The column assembly appends to every cells row: the row's resolution-3 parent.
BLOCK = "block"


def represented(table: pa.Table, block: str, grid: H3) -> int:
    """Reference cells the stored rows stand for once compacted rows are expanded.

    Only a pentagon block holds a pentagon, which has fewer children than 7 per level.
    """
    finest = grid.cell_resolution
    if h3.is_pentagon(int(block, 16)):
        keys = table.column("h3_uint64").to_pylist()
        return sum(h3.cell_to_children_size(key, finest) for key in keys)
    resolution = pc.cast(table.column("h3_resolution"), pa.int64())
    levels = pc.subtract(pa.scalar(finest, pa.int64()), resolution)
    return int(pc.sum(pc.power(pa.scalar(7, pa.int64()), levels)).as_py())


def index_row(
    record: Row, block: str, row_group: int | None, rows: int, cells: int
) -> Row:
    """One blocks-table row: where a covered block's cells are and how many."""
    return {
        BLOCK: block,
        "cell_group": PurePosixPath(record["path"]).parent.name.removeprefix("group="),
        "path": record["path"],
        "row_group": row_group,
        "row_count": rows,
        "reference_cells": cells,
    }


def sorted_blocks(rows: list[Row]) -> list[Row]:
    return sorted(rows, key=lambda row: int(row[BLOCK], 16))


def validate_block(batch: pa.RecordBatch, block: str, grid: H3) -> None:
    resolution = batch.column("h3_resolution")
    valid = pc.and_(
        Selection((), (block,), grid).spatial(batch),
        pc.and_(
            pc.greater_equal(resolution, pa.scalar(grid.block_resolution)),
            pc.less_equal(resolution, pa.scalar(grid.cell_resolution)),
        ),
    )
    complete = cast(pa.BooleanArray, pc.fill_null(valid, pa.scalar(False)))
    if not pc.all(complete).as_py():
        raise ValueError(f"Cells do not belong to declared block: {block}")


class CellGroups:
    """Buffer at most one block's reference cells, independent of batch size."""

    def __init__(self, writer: pq.ParquetWriter, schema: pa.Schema, grid: H3) -> None:
        self.writer = writer
        self.schema = schema
        self.grid = grid
        self.blocks: list[Row] = []
        # Reference cells per stored block, for the blocks table.
        self.reference: dict[str, int] = {}
        # Covered blocks without selected rows: ocean answers no_land, not
        # outside_coverage, exactly as a legacy zero-row block file did.
        self.empty_blocks: list[str] = []
        self.block = ""
        self.last = -1
        self.batches: list[pa.RecordBatch] = []
        self.rows = 0

    def _advance(self, block: str) -> None:
        if int(block, 16) <= self.last:
            raise ValueError("Cell blocks must be written in ascending order")
        self.last = int(block, 16)

    def empty(self, block: str) -> None:
        block = f"{int(block, 16):x}"
        self._advance(block)
        self.empty_blocks.append(block)

    def add(self, block: str, batch: pa.RecordBatch) -> None:
        block = f"{int(block, 16):x}"
        if self.block != block:
            self._advance(block)
            self.finish()
            self.block = block
        validate_block(batch, block, self.grid)
        self.rows += batch.num_rows
        if self.rows > h3.cell_to_children_size(
            int(block, 16), self.grid.cell_resolution
        ):
            raise ValueError(f"Cell block exceeds its reference cell count: {block}")
        column = pa.repeat(pa.scalar(block, pa.string()), batch.num_rows)
        self.batches.append(batch.append_column(self.schema.field(BLOCK), column))

    def finish(self) -> None:
        if not self.rows:
            return
        table = pa.Table.from_batches(self.batches, schema=self.schema)
        # A key's block fixes its row group, so per-block uniqueness is global.
        if pc.count_distinct(table.column("h3_uint64")).as_py() != self.rows:
            raise ValueError(f"Repeated cell key in block {self.block}")
        self.writer.write_table(table, row_group_size=self.rows)
        self.blocks.append(
            {"block": self.block, "row_group": len(self.blocks), "rows": self.rows}
        )
        self.reference[self.block] = represented(table, self.block, self.grid)
        self.batches.clear()
        self.rows = 0


def _parent(record: Row, block: int, grid: H3) -> None:
    group = PurePosixPath(record["path"]).parent.name
    if not group.startswith("group="):
        raise ValueError("Nonempty cells file must declare its parent group")
    parent = int(group.removeprefix("group="), 16)
    if (
        not h3.is_valid_cell(parent)
        or h3.get_resolution(parent) > grid.block_resolution
        or h3.cell_to_parent(block, h3.get_resolution(parent)) != parent
    ):
        raise ValueError("Cell block index differs from its file's parent group")


def _block(block: object, grid: H3, previous: int, seen: set[str]) -> int:
    if not isinstance(block, str):
        raise ValueError("Cell block index must contain unique sorted block IDs")
    value = int(block, 16)
    if (
        not h3.is_valid_cell(value)
        or h3.get_resolution(value) != grid.block_resolution
        or block != f"{value:x}"
        or value <= previous
        or block in seen
    ):
        raise ValueError("Cell block index must contain unique sorted block IDs")
    return value


def verify_empty(record: Row, grid: H3, seen: set[str]) -> list[Row]:
    empty = record.get("empty_blocks", [])
    if not isinstance(empty, list):
        raise ValueError("Cell empty_blocks must be a list")
    previous = -1
    for block in empty:
        previous = _block(block, grid, previous, seen)
        _parent(record, previous, grid)
        seen.add(block)
    return [index_row(record, block, None, 0, 0) for block in empty]


def verify_index(
    record: Row, file: pq.ParquetFile, grid: H3, seen: set[str]
) -> list[Row]:
    """Check one cells file against its manifest index; return its blocks rows."""
    blocks = record.get("blocks")
    if not isinstance(blocks, list) or len(blocks) != file.num_row_groups:
        raise ValueError(f"Cell block index differs from row groups: {record['path']}")
    # Datasets assembled before the block column existed lack it.
    names = ["h3_uint64", "h3_resolution"]
    names += [BLOCK] if BLOCK in file.schema_arrow.names else []
    rows = []
    previous = -1
    for number, entry in enumerate(blocks):
        if (
            not isinstance(entry, dict)
            or set(entry) != {"block", "row_group", "rows"}
            or not isinstance(entry["block"], str)
            or type(entry["row_group"]) is not int
            or type(entry["rows"]) is not int
            or entry["row_group"] != number
            or entry["rows"] <= 0
            or entry["rows"] != file.metadata.row_group(number).num_rows
        ):
            raise ValueError("Cell block index has invalid row group coordinates")
        block = entry["block"]
        value = _block(block, grid, previous, seen)
        if entry["rows"] > h3.cell_to_children_size(value, grid.cell_resolution):
            raise ValueError("Cell row group exceeds its reference cell count")
        _parent(record, value, grid)
        table = file.read_row_group(number, columns=names)
        for batch in table.to_batches():
            validate_block(batch, block, grid)
        if BLOCK in names and table.column(BLOCK).unique().to_pylist() != [block]:
            raise ValueError(f"Cell block column differs from its row group: {block}")
        cells = represented(table, block, grid)
        rows.append(index_row(record, block, number, entry["rows"], cells))
        previous = value
        seen.add(block)
    return rows + verify_empty(record, grid, seen)

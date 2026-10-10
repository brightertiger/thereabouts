"""Stream verified partitions into stable, coalesced release tables."""

from collections import defaultdict
from pathlib import Path
from typing import IO, Any, Literal, cast

import pyarrow as pa
import pyarrow.parquet as pq
from h3.api import basic_int as h3

from pipeline.config.release import DatasetLimits
from pipeline.engines.artifact_io import file_record

from .budget import Budget, Sink
from .cell_groups import BLOCK, CellGroups, index_row, sorted_blocks
from .dataset_schema import inputs, load, public
from .selection import Selection
from .source import Row, Snapshot, TableFile

# What assembly computes: columns appended to an input table, and whole tables.
APPENDED = {"cells": (BLOCK,)}
BLOCKS = "blocks"


def schema_description(path: Path) -> dict[str, Any]:
    """The validated schema as a released manifest embeds it."""
    return public(load(path))


def groups(
    snapshot: Snapshot, selection: Selection, limits: DatasetLimits
) -> dict[str, list[TableFile]]:
    result: dict[str, list[TableFile]] = defaultdict(list)
    for kind, records in sorted(snapshot.tables.items()):
        for record in sorted(
            records, key=lambda item: (int(item.block or "0", 16), item.path)
        ):
            if not selection.includes(record):
                continue
            partition = ""
            if kind == "cells":
                parent = h3.cell_to_parent(
                    int(record.block, 16), limits.cell_group_resolution
                )
                partition = f"/group={parent:x}"
            elif record.country:
                partition = f"/country={record.country}"
            result[f"{kind}{partition}/part.parquet"].append(record)
        # Empty tables remain readable and retain their declared schema.
        if not any(path.startswith(kind + "/") for path in result):
            result[f"{kind}/part.parquet"] = []
    return dict(result)


def validate_schema(
    schema: pa.Schema, description: Row, kind: str, what: str = "Input"
) -> None:
    actual = [
        {"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in schema
    ]
    expected = [
        {key: column[key] for key in ("name", "type", "nullable")}
        for column in description["columns"]
    ]
    if actual != expected:
        raise ValueError(f"{what} schema differs from config/dataset.yaml: {kind}")


def field(column: Row) -> "pa.Field[pa.DataType]":
    kind = pa.type_for_alias(column["type"])
    return pa.field(column["name"], kind, nullable=column["nullable"])


def published(schema: pa.Schema, description: Row, kind: str) -> pa.Schema:
    """The input schema with the columns assembly appends, in declared order."""
    extra = [column for column in description["columns"] if column.get("assembled")]
    if tuple(column["name"] for column in extra) != APPENDED.get(kind, ()):
        raise ValueError(f"No assembly rule computes the declared columns of {kind}")
    return pa.schema([*schema, *map(field, extra)])


def parquet(sink: Sink, schema: pa.Schema, limits: DatasetLimits) -> pq.ParquetWriter:
    return pq.ParquetWriter(
        cast(IO[bytes], sink),
        schema,
        compression=cast(Literal["zstd", "snappy"], limits.compression),
    )


def block_index(
    output: Path,
    tables: list[Row],
    reference: dict[str, int],
    description: Row,
    limits: DatasetLimits,
    budget: Budget,
) -> Row:
    """The manifest's cell block index, published as the blocks table."""
    rows = []
    for table in tables:
        if table["kind"] != "cells":
            continue
        for entry in table["blocks"]:
            block, stored = entry[BLOCK], entry["rows"]
            cells = reference[block]
            rows.append(index_row(table, block, entry["row_group"], stored, cells))
        rows += [index_row(table, block, None, 0, 0) for block in table["empty_blocks"]]
    schema = pa.schema(map(field, description["columns"]))
    path = output / BLOCKS / "part.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    with Sink(path, budget) as sink, parquet(sink, schema, limits) as writer:
        if rows:
            writer.write_table(
                pa.Table.from_pylist(sorted_blocks(rows), schema=schema),
                row_group_size=limits.row_group_rows,
            )
    validate_schema(pq.read_schema(path), description, BLOCKS, "Written")
    return {**file_record(output, path), "kind": BLOCKS, "rows": len(rows)}


def assemble_tables(
    snapshot: Snapshot,
    output: Path,
    selection: Selection,
    limits: DatasetLimits,
    descriptions: Row,
    budget: Budget,
) -> tuple[list[Row], set[str], set[str]]:
    expected = inputs(descriptions)
    if set(snapshot.tables) != set(expected):
        raise ValueError("Dataset schema and input table names differ")
    if set(descriptions) - set(expected) != {BLOCKS}:
        raise ValueError("No assembly rule builds the declared assembled tables")
    tables: list[Row] = []
    sources: set[str] = set()
    row_licences: set[str] = set()
    reference: dict[str, int] = {}
    for relative, records in groups(snapshot, selection, limits).items():
        kind = relative.split("/")[0]
        schema = pq.read_schema(snapshot.verify(snapshot.tables[kind][0]))
        validate_schema(schema, expected[kind], kind)
        schema = published(schema, descriptions[kind], kind)
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = 0
        pending: list[pa.RecordBatch] = []
        pending_rows = 0
        with Sink(path, budget) as sink, parquet(sink, schema, limits) as writer:
            cell_groups = (
                CellGroups(writer, schema, selection.grid) if kind == "cells" else None
            )
            for record in records:
                before = rows
                original = snapshot.verify(record)
                with pq.ParquetFile(original) as file:
                    validate_schema(file.schema_arrow, expected[kind], kind)
                    for batch in file.iter_batches(batch_size=limits.batch_rows):
                        selected = selection.filter(kind, batch)
                        if not selected.num_rows:
                            continue
                        for key in descriptions[kind]["primary_key"]:
                            if selected.column(key).null_count:
                                raise ValueError(
                                    f"Null logical primary key: {kind}.{key}"
                                )
                        if "source" in selected.schema.names:
                            sources.update(
                                value
                                for value in selected.column("source").to_pylist()
                                if value
                            )
                        if "license" in selected.schema.names:
                            row_licences.update(
                                value
                                for value in selected.column("license").to_pylist()
                                if value
                            )
                        rows += selected.num_rows
                        if cell_groups is not None:
                            cell_groups.add(record.block, selected)
                            continue
                        pending.append(selected)
                        pending_rows += selected.num_rows
                        if pending_rows >= limits.row_group_rows:
                            writer.write_table(
                                pa.Table.from_batches(pending, schema=schema),
                                row_group_size=limits.row_group_rows,
                            )
                            pending.clear()
                            pending_rows = 0
                snapshot.verify(record)
                if cell_groups is not None and rows == before:
                    cell_groups.empty(record.block)
            if cell_groups is not None:
                cell_groups.finish()
            if pending:
                writer.write_table(
                    pa.Table.from_batches(pending, schema=schema),
                    row_group_size=limits.row_group_rows,
                )
        if pq.read_metadata(path).num_rows != rows:
            raise ValueError(f"Written row count differs: {relative}")
        validate_schema(pq.read_schema(path), descriptions[kind], kind, "Written")
        entry: Row = {**file_record(output, path), "kind": kind, "rows": rows}
        if cell_groups is not None:
            entry["blocks"] = cell_groups.blocks
            entry["empty_blocks"] = cell_groups.empty_blocks
            reference |= cell_groups.reference
        tables.append(entry)
    tables.append(
        block_index(output, tables, reference, descriptions[BLOCKS], limits, budget)
    )
    return tables, sources, row_licences

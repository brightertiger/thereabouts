"""Stream verified partitions into stable, coalesced release tables."""

from collections import defaultdict
from pathlib import Path
from typing import IO, Any, Literal, cast

import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from h3.api import basic_int as h3

from pipeline.config.release import DatasetLimits
from pipeline.engines.artifact_io import file_record

from .budget import Budget, Sink
from .cell_groups import CellGroups
from .selection import Selection
from .source import Row, Snapshot, TableFile


def schema_description(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict) or not value:
        raise ValueError("Dataset schema must declare its tables")
    return value


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


def validate_schema(schema: pa.Schema, description: Row, kind: str) -> None:
    actual = [
        {"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in schema
    ]
    expected = [
        {key: column[key] for key in ("name", "type", "nullable")}
        for column in description["columns"]
    ]
    if actual != expected:
        raise ValueError(f"Input schema differs from config/dataset.yaml: {kind}")


def assemble_tables(
    snapshot: Snapshot,
    output: Path,
    selection: Selection,
    limits: DatasetLimits,
    descriptions: Row,
    budget: Budget,
) -> tuple[list[Row], set[str], set[str]]:
    if set(snapshot.tables) != set(descriptions):
        raise ValueError("Dataset schema and input table names differ")
    tables: list[Row] = []
    sources: set[str] = set()
    row_licences: set[str] = set()
    for relative, records in groups(snapshot, selection, limits).items():
        kind = relative.split("/")[0]
        schema = pq.read_schema(snapshot.verify(snapshot.tables[kind][0]))
        validate_schema(schema, descriptions[kind], kind)
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = 0
        pending: list[pa.RecordBatch] = []
        pending_rows = 0
        with (
            Sink(path, budget) as sink,
            pq.ParquetWriter(
                cast(IO[bytes], sink),
                schema,
                compression=cast(Literal["zstd", "snappy"], limits.compression),
            ) as writer,
        ):
            cell_groups = (
                CellGroups(writer, schema, selection.grid) if kind == "cells" else None
            )
            for record in records:
                original = snapshot.verify(record)
                with pq.ParquetFile(original) as file:
                    validate_schema(file.schema_arrow, descriptions[kind], kind)
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
            if cell_groups is not None:
                cell_groups.finish()
            if pending:
                writer.write_table(
                    pa.Table.from_batches(pending, schema=schema),
                    row_group_size=limits.row_group_rows,
                )
        if pq.read_metadata(path).num_rows != rows:
            raise ValueError(f"Written row count differs: {relative}")
        entry: Row = {**file_record(output, path), "kind": kind, "rows": rows}
        if cell_groups is not None:
            entry["blocks"] = cell_groups.blocks
        tables.append(entry)
    return tables, sources, row_licences

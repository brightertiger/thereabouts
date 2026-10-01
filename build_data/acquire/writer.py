"""Bounded row batching for every adapter; publication always validates Parquet."""

from collections.abc import Mapping
from pathlib import Path

import pyarrow as pa

from .parquet import write_partition
from .runtime import source_budget
from .schemas import SCHEMAS, Kind
from .workspace import Workspace

DEFAULT_BATCH_BYTES = 12_000_000
DEFAULT_PART_BYTES = 48_000_000
DEFAULT_BATCH_ROWS = 512


class PartitionWriter:
    """Buffer a bounded batch and rotate partitions at a conservative byte target.

    Estimates control buffering; the shared Parquet writer enforces actual row,
    batch, decoded and encoded limits before publishing any file. Estimation
    options preserve each original adapter's partition boundaries on rebuild.
    """

    def __init__(
        self,
        workspace: Workspace,
        source: str,
        kind: Kind,
        unit: str,
        digest: str,
        *,
        batch_bytes: int = DEFAULT_BATCH_BYTES,
        part_bytes: int = DEFAULT_PART_BYTES,
        batch_rows: int = DEFAULT_BATCH_ROWS,
        overhead: int = 0,
        scalar_bytes: int = 16,
        estimate_fields: tuple[str, ...] | None = None,
    ) -> None:
        self.workspace, self.source, self.kind = workspace, source, kind
        self.unit, self.digest = unit, digest
        self.batch_bytes, self.part_bytes, self.batch_rows = (
            batch_bytes,
            part_bytes,
            batch_rows,
        )
        self.overhead, self.scalar_bytes, self.estimate_fields = (
            overhead,
            scalar_bytes,
            estimate_fields,
        )
        self.rows: list[dict[str, object]] = []
        self.tables: list[pa.Table] = []
        self.estimate = self.size = self.count = self.decoded_bytes = 0
        self.outputs: list[Path] = []

    def add(self, row: Mapping[str, object]) -> None:
        values = (
            (row[k] for k in self.estimate_fields)
            if self.estimate_fields
            else iter(row.values())
        )
        size = self.overhead + sum(
            len(value.encode("utf-8"))
            if isinstance(value, str)
            else len(value)
            if isinstance(value, bytes)
            else self.scalar_bytes
            for value in values
        )
        if self.rows and (
            self.estimate + size > self.batch_bytes or len(self.rows) >= self.batch_rows
        ):
            self._batch()
        self.rows.append(dict(row))
        self.estimate += size
        self.count += 1

    def _batch(self) -> None:
        if not self.rows:
            return
        table = pa.Table.from_pylist(self.rows, schema=SCHEMAS[self.kind])
        if self.tables and self.size + table.nbytes > self.part_bytes:
            self._publish()
        self.tables.append(table)
        self.size += table.nbytes
        self.decoded_bytes += table.nbytes
        self.rows, self.estimate = [], 0

    def _publish(self) -> None:
        if not self.tables:
            return
        source_budget(self.workspace, self.source, self.size * 2)
        path = self.workspace.partition(
            self.source, self.kind, self.unit, self.digest, len(self.outputs)
        )
        write_partition(path, self.kind, self.tables)
        self.outputs.append(path)
        self.tables, self.size = [], 0

    def finish(self) -> list[Path]:
        self._batch()
        self._publish()
        return self.outputs

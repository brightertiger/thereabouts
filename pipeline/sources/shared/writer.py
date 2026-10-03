"""One bounded partition stream within a source unit."""

from collections.abc import Mapping
from pathlib import Path

import pyarrow as pa

from pipeline.runtime.jsonio import digest
from pipeline.sources.contract import SourceContext

from .parquet import write_partition
from .schemas import SCHEMAS, Kind


class PartitionWriter:
    def __init__(self, ctx: SourceContext, kind: Kind, key: str) -> None:
        self.ctx, self.kind, self.key = ctx, kind, key
        self.rows: list[dict[str, object]] = []
        self.tables: list[pa.Table] = []
        self.estimate = self.size = self.count = 0
        self.outputs: list[Path] = []

    def add(self, row: Mapping[str, object]) -> None:
        limits = self.ctx.settings.limits
        size = limits.row_overhead + sum(
            self._estimate(value) for value in row.values()
        )
        if size > limits.row_bytes or size > limits.batch_bytes:
            raise ValueError("Source row exceeds its configured byte limit")
        if self.rows and (
            self.estimate + size > limits.batch_bytes
            or len(self.rows) >= limits.batch_rows
        ):
            self._batch()
        self.rows.append(dict(row))
        self.estimate += size
        self.count += 1

    def _estimate(self, value: object) -> int:
        if isinstance(value, str):
            return len(value.encode("utf-8"))
        if isinstance(value, bytes):
            return len(value)
        if isinstance(value, (tuple, list)):
            return sum(self._estimate(item) for item in value)
        if isinstance(value, dict):
            return sum(self._estimate(item) for item in value.values())
        return self.ctx.settings.limits.scalar_bytes

    def _batch(self) -> None:
        if not self.rows:
            return
        table = pa.Table.from_pylist(self.rows, schema=SCHEMAS[self.kind])
        if (
            self.tables
            and self.size + table.nbytes > self.ctx.settings.limits.part_bytes
        ):
            self._publish()
        self.tables.append(table)
        self.size += table.nbytes
        self.rows, self.estimate = [], 0

    def _publish(self) -> None:
        if not self.tables:
            return
        path = (
            self.ctx.normalized
            / self.kind
            / self.ctx.unit.inputs_hash
            / f"{digest(self.key)}-{len(self.outputs):05d}.parquet"
        )
        path = self.ctx.ensure(path)
        guard = self.ctx.runtime.guard
        reservation = self.size * 2
        guard.admit(reservation)
        written = 0
        try:
            write_partition(
                path,
                self.kind,
                self.ctx.settings.name,
                self.ctx.settings.limits,
                self.tables,
            )
            written = path.stat().st_size
            self.outputs.append(path)
        finally:
            guard.release(reservation, written_bytes=written)
        self.tables, self.size = [], 0

    def finish(self) -> list[Path]:
        self._batch()
        self._publish()
        return self.outputs

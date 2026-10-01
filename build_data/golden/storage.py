"""Bounded Parquet publication and the golden stage's independent disk budget."""

from __future__ import annotations

import shutil
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from build_data.acquire import Workspace, atomic_output
from build_data.acquire.artifacts import file_record
from build_data.acquire.runtime import disk_bytes
from build_data.reconcile.common import Row

LIMIT = 8_000_000_000
RESERVE = 13_000_000_000
_usage: dict[Path, tuple[float, int, int]] = {}


class DiskBudgetExceeded(OSError):
    """A resumable pause; other I/O failures must still fail visibly."""


def budget(workspace: Workspace, required: int = 64_000_000) -> None:
    stamp, used, reserved = _usage.get(workspace.root, (0.0, 0, 0))
    if time.monotonic() - stamp > 30 or used + reserved + required > LIMIT:
        used = sum(
            disk_bytes(p.rglob("*"))
            for p in (workspace.root / "golden", workspace.work / "golden")
        )
        stamp, reserved = time.monotonic(), 0
    free = shutil.disk_usage(workspace.root).free
    if used + required > LIMIT or free - required < RESERVE:
        raise DiskBudgetExceeded(
            f"Golden disk guard: used={used:,}, free={free:,}, need={required:,}"
        )
    _usage[workspace.root] = stamp, used, reserved + required


def batches(rows: Iterable[Row], size: int = 1024) -> Iterator[list[Row]]:
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def check_parquet(path: Path) -> None:
    pq.read_metadata(path)


def parquet(path: Path, rows: Iterable[Row], schema: pa.Schema) -> Row:
    count = 0
    with (
        atomic_output(path, check_parquet) as temporary,
        pq.ParquetWriter(temporary, schema, compression="zstd") as writer,
    ):
        for group in batches(rows):
            table = pa.Table.from_pylist(group, schema=schema)
            writer.write_table(table)
            count += len(group)
    return {**file_record(path), "rows": count}

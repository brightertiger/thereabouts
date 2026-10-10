"""Refuse a release that repeats a declared logical primary key.

Assembly already rejects null key values. Here each keyed table's key values are
hashed and sorted in bounded scratch, as the logical digest sorts its rows. Cells
are checked per block while their row groups are written (`cell_groups.py`).
"""

import hashlib
import json
import tempfile
from pathlib import Path

import pyarrow.parquet as pq

from pipeline.config.content import DigestLimits
from pipeline.content.digest import canonical
from pipeline.content.sorting import WIDTH, RowHashes
from pipeline.runtime.resources import ResourceGuard

from .source import Row

# A cell key's block fixes its row group, so these are unique as written.
CHECKED_WHEN_WRITTEN = {"cells"}


def hashed(values: tuple[object, ...]) -> bytes:
    encoded = json.dumps(
        [canonical(value) for value in values],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()


def repeats(
    paths: list[Path], key: list[str], scratch: Path, limits: DigestLimits
) -> bool:
    with tempfile.TemporaryDirectory(prefix=".keys-", dir=scratch) as work:
        sorter = RowHashes(Path(work) / "runs", limits)
        for path in paths:
            with pq.ParquetFile(path) as file:
                for batch in file.iter_batches(
                    batch_size=limits.batch_rows, columns=key
                ):
                    columns = [batch.column(name).to_pylist() for name in key]
                    sorter.add(hashed(values) for values in zip(*columns, strict=True))
        return any(count > 1 for _, count in sorter.counts())


def check(
    directory: Path,
    tables: list[Row],
    descriptions: Row,
    limits: DigestLimits,
    guard: ResourceGuard,
) -> None:
    """Raise naming the first table whose declared key repeats."""
    for kind, description in descriptions.items():
        key = description["primary_key"]
        if not key or kind in CHECKED_WHEN_WRITTEN:
            continue
        records = [table for table in tables if table["kind"] == kind]
        # One live sorted run plus one merge output, released per table.
        scratch_bytes = 2 * WIDTH * sum(record["rows"] for record in records)
        guard.admit(scratch_bytes)
        try:
            paths = [directory / record["path"] for record in records]
            if repeats(paths, key, directory, limits):
                raise ValueError(
                    f"Repeated logical primary key: {kind} ({', '.join(key)})"
                )
        finally:
            guard.release(scratch_bytes, written_bytes=0)

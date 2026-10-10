"""Refuse a release that repeats a declared logical primary key.

Assembly already rejects null key values. Here each keyed table's key values are
hashed and sorted in bounded scratch, as the logical digest sorts its rows. Cells
are checked per block while their row groups are written (`cell_groups.py`).
"""

import hashlib
import json
import tempfile
from collections.abc import Iterator
from itertools import islice
from pathlib import Path

import pyarrow.parquet as pq

from pipeline.config.content import DigestLimits
from pipeline.content.digest import canonical
from pipeline.content.sorting import WIDTH, RowHashes
from pipeline.runtime.resources import ResourceGuard

from .source import Row

# A cell key's block fixes its row group, so these are unique as written.
CHECKED_WHEN_WRITTEN = {"cells"}
# Repeated key values named in the error, so they can be found in the inputs.
EXAMPLES = 5


def hashed(values: tuple[object, ...]) -> bytes:
    encoded = json.dumps(
        [canonical(value) for value in values],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()


def values(
    paths: list[Path], key: list[str], limits: DigestLimits
) -> Iterator[tuple[object, ...]]:
    for path in paths:
        with pq.ParquetFile(path) as file:
            for batch in file.iter_batches(batch_size=limits.batch_rows, columns=key):
                columns = [batch.column(name).to_pylist() for name in key]
                yield from zip(*columns, strict=True)


def repeats(
    paths: list[Path], key: list[str], scratch: Path, limits: DigestLimits
) -> list[tuple[object, ...]]:
    """Up to `EXAMPLES` key values that occur more than once, by digest order."""
    with tempfile.TemporaryDirectory(prefix=".keys-", dir=scratch) as work:
        sorter = RowHashes(Path(work) / "runs", limits)
        sorter.add(hashed(row) for row in values(paths, key, limits))
        repeated = list(
            islice((digest for digest, count in sorter.counts() if count > 1), EXAMPLES)
        )
    # Digests cannot be reversed; a second pass finds the values they stand for.
    found: dict[bytes, tuple[object, ...]] = {}
    if repeated:
        for row in values(paths, key, limits):
            digest = hashed(row)
            if digest in repeated and digest not in found:
                found[digest] = row
                if len(found) == len(repeated):
                    break
    return [found[digest] for digest in repeated]


def check(
    directory: Path,
    tables: list[Row],
    descriptions: Row,
    limits: DigestLimits,
    guard: ResourceGuard,
) -> None:
    """Raise naming the first table whose declared key repeats, with examples."""
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
            examples = repeats(paths, key, directory, limits)
        finally:
            guard.release(scratch_bytes, written_bytes=0)
        if examples:
            raise ValueError(
                f"Repeated logical primary key: {kind} ({', '.join(key)}); "
                f"repeated values: {'; '.join(map(repr, examples))}"
            )

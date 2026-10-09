"""Bounded GeoNames TSV reading and structural field parsing."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pipeline.sources.shared.rows import RowRejected


@dataclass(frozen=True)
class Chunk:
    start: int
    end: int


def chunks(path: Path, chunk_bytes: int, line_bytes: int) -> Iterator[Chunk]:
    """Find complete-line byte intervals without decoding or loading a TSV."""
    size = path.stat().st_size
    start = 0
    with path.open("rb") as stream:
        while start < size:
            stream.seek(min(size, start + chunk_bytes))
            if stream.tell() < size:
                stream.readline(line_bytes + 1)
            end = stream.tell()
            yield Chunk(start, end)
            start = end


def lines(path: Path, chunk: Chunk, line_bytes: int) -> Iterator[tuple[int, bytes]]:
    with path.open("rb") as stream:
        stream.seek(chunk.start)
        while stream.tell() < chunk.end:
            offset = stream.tell()
            raw = stream.readline(line_bytes + 1)
            if len(raw) > line_bytes:
                raise ValueError(f"Oversized raw TSV line at {path}:{offset}")
            yield offset, raw


def fields(raw: bytes, count: int) -> list[str]:
    values = raw.decode("utf-8").rstrip("\r\n").split("\t")
    if len(values) != count:
        raise RowRejected(f"Expected {count} fields, got {len(values)}")
    return values

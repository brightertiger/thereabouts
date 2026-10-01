"""Bounded GeoNames TSV reading and structural field parsing."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

CHUNK_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 1_000_000


@dataclass(frozen=True)
class Chunk:
    start: int
    end: int


def chunks(path: Path) -> Iterator[Chunk]:
    """Find complete-line byte intervals without decoding or loading a TSV."""
    size = path.stat().st_size
    start = 0
    with path.open("rb") as stream:
        while start < size:
            stream.seek(min(size, start + CHUNK_BYTES))
            if stream.tell() < size:
                stream.readline(MAX_LINE_BYTES + 1)
            end = stream.tell()
            yield Chunk(start, end)
            start = end


def lines(path: Path, chunk: Chunk) -> Iterator[tuple[int, bytes]]:
    with path.open("rb") as stream:
        stream.seek(chunk.start)
        while stream.tell() < chunk.end:
            offset = stream.tell()
            raw = stream.readline(MAX_LINE_BYTES + 1)
            if len(raw) > MAX_LINE_BYTES:
                raise ValueError(f"Oversized raw TSV line at {path}:{offset}")
            yield offset, raw


def fields(raw: bytes, count: int) -> list[str]:
    if len(raw) > MAX_LINE_BYTES:
        raise ValueError("TSV line exceeds the 1 MB audited row limit")
    values = raw.decode("utf-8").rstrip("\r\n").split("\t")
    if len(values) != count:
        raise ValueError(f"Expected {count} fields, got {len(values)}")
    return values

"""Validate section bounds before exposing an immutable memory mapping."""

import mmap
from dataclasses import dataclass
from pathlib import Path

from .errors import CorruptPackError, UnsupportedPackError
from .layout import HEADER, MAGIC, MAJOR, MINOR, SECTION, SECTIONS, WIDTHS, aligned


@dataclass(frozen=True)
class Span:
    offset: int
    size: int
    count: int


class Container:
    def __init__(self, path: Path, kind: int) -> None:
        with path.open("rb") as stream:
            if path.stat().st_size < HEADER.size:
                raise CorruptPackError("Truncated container header")
            self.data = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            self.sections = self._sections(kind)
        except (ValueError, CorruptPackError, UnsupportedPackError):
            self.close()
            raise

    def _sections(self, kind: int) -> dict[int, Span]:
        magic, major, minor, flags, actual_kind, count, size = HEADER.unpack_from(
            self.data
        )
        if magic != MAGIC:
            raise CorruptPackError("Invalid container magic")
        if (major, minor) != (MAJOR, MINOR) or flags:
            raise UnsupportedPackError(
                "Unsupported serving format or required features"
            )
        if (
            actual_kind != kind
            or count != len(SECTIONS[kind])
            or size != len(self.data)
        ):
            raise CorruptPackError("Invalid container kind, length or section count")
        end = HEADER.size + count * SECTION.size
        if end > size:
            raise CorruptPackError("Truncated section directory")
        result = {}
        for ordinal, expected in enumerate(SECTIONS[kind]):
            section, flags, offset, length, rows = SECTION.unpack_from(
                self.data, HEADER.size + ordinal * SECTION.size
            )
            if (
                section != expected
                or flags
                or offset != aligned(end)
                or length != rows * WIDTHS[section]
                or offset + length > size
            ):
                raise CorruptPackError("Invalid section directory or bounds")
            if any(self.data[end:offset]):
                raise CorruptPackError("Nonzero section padding")
            result[section] = Span(offset, length, rows)
            end = offset + length
        if end != size:
            raise CorruptPackError("Unexpected trailing bytes")
        return result

    def close(self) -> None:
        self.data.close()

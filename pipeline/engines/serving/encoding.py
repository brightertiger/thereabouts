"""Deterministic binary serialization and bounded shard buffers."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pipeline.pack_format.container import Container
from pipeline.pack_format.layout import (
    CATALOGUE,
    HEADER,
    MAGIC,
    MAJOR,
    MINOR,
    OFFSETS,
    PLACE,
    PLACES,
    REFERENCE_FIELDS,
    SECTION,
    SECTIONS,
    TEXT,
    TEXT_FIELDS,
    U64,
    WIDTHS,
    aligned,
)
from pipeline.runtime.jsonio import atomic_output


def write_container(
    path: Path, kind: int, sections: Mapping[int, bytes | bytearray]
) -> None:
    end = HEADER.size + SECTION.size * len(sections)
    directory = bytearray()
    for number in SECTIONS[kind]:
        data = sections[number]
        offset = aligned(end)
        if len(data) % WIDTHS[number]:
            raise ValueError("Misaligned record buffer")
        directory += SECTION.pack(
            number, 0, offset, len(data), len(data) // WIDTHS[number]
        )
        end = offset + len(data)

    with atomic_output(path) as temporary:
        with temporary.open("wb") as stream:
            stream.write(HEADER.pack(MAGIC, MAJOR, MINOR, 0, kind, len(sections), end))
            stream.write(directory)
            for number in SECTIONS[kind]:
                stream.write(bytes(aligned(stream.tell()) - stream.tell()))
                stream.write(sections[number])
        Container(temporary, kind).close()


class CatalogueBuffer:
    def __init__(self) -> None:
        self.records = bytearray()
        self.offsets = bytearray(U64.pack(0) + U64.pack(0))
        self.text = bytearray()
        self.strings: dict[str, int] = {}

    @property
    def size(self) -> int:
        return len(self.records) + len(self.offsets) + len(self.text)

    def add(self, row: dict[str, Any]) -> None:
        refs = []
        for name in TEXT_FIELDS:
            value = row[name]
            if value is None:
                refs.append(0)
                continue
            if value not in self.strings:
                self.strings[value] = len(self.strings) + 1
                self.text.extend(value.encode("utf-8"))
                self.offsets.extend(U64.pack(len(self.text)))
            refs.append(self.strings[value])
        refs.extend(row[name] for name in REFERENCE_FIELDS)
        self.records.extend(PLACE.pack(*refs))

    def write(self, path: Path) -> None:
        write_container(
            path,
            CATALOGUE,
            {PLACES: self.records, OFFSETS: self.offsets, TEXT: self.text},
        )

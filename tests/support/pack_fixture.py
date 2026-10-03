"""Small malformed decoder fixtures; every format constant comes from the client."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from thereabouts.packs.jsonio import canonical, sha256
from thereabouts.packs.layout import (
    CODE_INDEX,
    CODE_KEYS,
    CODE_PAYLOADS,
    EXACT,
    HEADER,
    KEY_RECORD,
    MAGIC,
    MAJOR,
    MINOR,
    SECTION,
    SECTIONS,
    WIDTHS,
    aligned,
)


def write_container(
    path: Path, kind: int, sections: Mapping[int, bytes | bytearray]
) -> None:
    end = HEADER.size + SECTION.size * len(sections)
    directory = bytearray()
    for number in SECTIONS[kind]:
        data = sections[number]
        offset = aligned(end)
        directory += SECTION.pack(
            number, 0, offset, len(data), len(data) // WIDTHS[number]
        )
        end = offset + len(data)
    with path.open("wb") as stream:
        stream.write(HEADER.pack(MAGIC, MAJOR, MINOR, 0, kind, len(sections), end))
        stream.write(directory)
        for number in SECTIONS[kind]:
            stream.write(bytes(aligned(stream.tell()) - stream.tell()))
            stream.write(sections[number])


def write_exact(path: Path, records: list[tuple[str, int, bytes, bytes]]) -> int:
    keys, payloads, directory = bytearray(), bytearray(), bytearray()
    maximum = 0
    for key, count, raw, compressed in records:
        encoded = key.encode()
        directory += KEY_RECORD.pack(
            len(keys), len(encoded), count, len(payloads), len(compressed), len(raw)
        )
        keys += encoded
        payloads += compressed
        maximum = max(maximum, len(raw))
    write_container(
        path, EXACT, {CODE_INDEX: directory, CODE_KEYS: keys, CODE_PAYLOADS: payloads}
    )
    return maximum


def file_record(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "sha256": sha256(path),
    }


def write_manifest(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(canonical(value))

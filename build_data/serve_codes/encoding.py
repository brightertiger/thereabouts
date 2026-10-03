"""Independently compressed exact records, sharded at complete-key boundaries."""

import zlib
from pathlib import Path

from build_data.serve.checkpoints import unit
from build_data.serve.encoding import write_container
from build_data.serve.snapshot import Row
from thereabouts.packs.exact import Exact
from thereabouts.packs.jsonio import canonical
from thereabouts.packs.layout import (
    CODE_INDEX,
    CODE_KEYS,
    CODE_PAYLOADS,
    EXACT,
    KEY_RECORD,
)

from .index import CodeIndex


class Buffer:
    def __init__(self) -> None:
        self.directory = bytearray()
        self.keys = bytearray()
        self.payloads = bytearray()
        self.first = self.last = ""
        self.maximum = 0

    @property
    def size(self) -> int:
        return len(self.directory) + len(self.keys) + len(self.payloads)

    def add(self, key: str, count: int, raw: bytes, compressed: bytes) -> None:
        self.maximum = max(self.maximum, len(raw))
        encoded = key.encode("utf-8")
        self.directory.extend(
            KEY_RECORD.pack(
                len(self.keys),
                len(encoded),
                count,
                len(self.payloads),
                len(compressed),
                len(raw),
            )
        )
        self.keys.extend(encoded)
        self.payloads.extend(compressed)
        if not self.first:
            self.first = key
        self.last = key

    def write(self, path: Path) -> None:
        write_container(
            path,
            EXACT,
            {
                CODE_INDEX: self.directory,
                CODE_KEYS: self.keys,
                CODE_PAYLOADS: self.payloads,
            },
        )


def shards(
    index: CodeIndex, work: Path, pack: Path, fingerprint: str, target: int
) -> list[Row]:
    result: list[Row] = []
    buffer = Buffer()

    def flush() -> None:
        fields = {
            "kind": "exact",
            "first_key": buffer.first,
            "last_key": buffer.last,
            "count": len(buffer.directory) // KEY_RECORD.size,
            "max_record_bytes": buffer.maximum,
        }
        result.append(
            unit(
                work,
                pack,
                f"exact-{len(result):05d}.bin",
                fingerprint,
                fields,
                buffer.write,
            )
        )

    for key, value in index.records():
        raw = canonical(value)
        compressed = zlib.compress(raw, level=6)
        added = len(key.encode("utf-8")) + KEY_RECORD.size + len(compressed)
        if buffer.directory and buffer.size + added > target:
            flush()
            buffer = Buffer()
        buffer.add(key, len(value["candidates"]), raw, compressed)
    if buffer.directory:
        flush()
    if not result:
        raise ValueError("Selected family contains no queryable codes")
    return result


def verify_source(index: CodeIndex, pack: Path, files: list[Row]) -> None:
    expected = iter(index.records())
    for record in files:
        if record["kind"] != "exact":
            continue
        shard = Exact(pack / record["path"], record["max_record_bytes"])
        try:
            for position in range(shard.count):
                key, value = next(expected)
                if (
                    shard.key(position) != key.encode("utf-8")
                    or shard.payload(position) != value
                ):
                    raise ValueError("Exact payload differs from golden observations")
        finally:
            shard.close()
    if next(expected, None) is not None:
        raise ValueError("Missing exported exact keys")

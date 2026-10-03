"""Exact-key directory with independently compressed candidate records."""

import zlib
from pathlib import Path
from typing import Any, cast

from .container import Container
from .errors import CorruptPackError
from .jsonio import parse
from .layout import CODE_INDEX, CODE_KEYS, CODE_PAYLOADS, EXACT, KEY_RECORD


class Exact(Container):
    def __init__(self, path: Path, maximum: int) -> None:
        super().__init__(path, EXACT)
        self.count = self.sections[CODE_INDEX].count
        try:
            key_end = payload_end = 0
            previous = b""
            for index in range(self.count):
                start, length, count, offset, size, raw = self.record(index)
                if (
                    start != key_end
                    or offset != payload_end
                    or not length
                    or not count
                    or not size
                    or not 0 < raw <= maximum
                    or start + length > self.sections[CODE_KEYS].size
                    or offset + size > self.sections[CODE_PAYLOADS].size
                ):
                    raise ValueError("Invalid exact-key spans")
                current = self.key(index)
                if current <= previous:
                    raise ValueError("Unsorted or repeated exact key")
                current.decode("utf-8")
                previous = current
                key_end, payload_end = start + length, offset + size
            if (
                not self.count
                or key_end != self.sections[CODE_KEYS].size
                or payload_end != self.sections[CODE_PAYLOADS].size
            ):
                raise ValueError("Incomplete exact-key directory")
        except ValueError as exc:
            self.close()
            raise CorruptPackError(str(exc)) from exc

    def record(self, index: int) -> tuple[int, int, int, int, int, int]:
        return cast(
            tuple[int, int, int, int, int, int],
            KEY_RECORD.unpack_from(
                self.data, self.sections[CODE_INDEX].offset + index * KEY_RECORD.size
            ),
        )

    def key(self, index: int) -> bytes:
        start, length, *_ = self.record(index)
        offset = self.sections[CODE_KEYS].offset + start
        return self.data[offset : offset + length]

    def position(self, key: str) -> int | None:
        target = key.encode("utf-8")
        lo, hi = 0, self.count
        while lo < hi:
            mid = (lo + hi) // 2
            if self.key(mid) < target:
                lo = mid + 1
            else:
                hi = mid
        return lo if lo < self.count and self.key(lo) == target else None

    def payload(self, index: int) -> dict[str, Any]:
        _, _, count, start, size, raw = self.record(index)
        offset = self.sections[CODE_PAYLOADS].offset + start
        decoder = zlib.decompressobj()
        try:
            data = decoder.decompress(self.data[offset : offset + size], raw + 1)
            if (
                len(data) != raw
                or not decoder.eof
                or decoder.unused_data
                or decoder.unconsumed_tail
            ):
                raise ValueError("Invalid exact payload decompressed size or framing")
            result = parse(data)
            if (
                not isinstance(result.get("candidates"), list)
                or len(result["candidates"]) != count
            ):
                raise ValueError("Exact candidate count mismatch")
            return result
        except (ValueError, OverflowError, zlib.error) as exc:
            raise CorruptPackError(str(exc)) from exc

"""Enforce release byte limits before every write, including Parquet footers."""

import io
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from pipeline.runtime.resources import ResourceGuard


@dataclass
class Budget:
    maximum: int
    guard: ResourceGuard
    written: int = 0

    def write(self, stream: BinaryIO, data: bytes) -> int:
        size = len(data)
        if self.written + size > self.maximum:
            raise ValueError(f"Release output cap exceeded: {self.maximum} bytes")
        self.guard.admit(size)
        written = 0
        try:
            written = stream.write(data)
            self.written += written
            return written
        finally:
            self.guard.release(size, written_bytes=written)

    def text(self, path: Path, value: str) -> None:
        with path.open("wb") as stream:
            self.write(stream, value.encode("utf-8"))


class Sink(io.RawIOBase):
    def __init__(self, path: Path, budget: Budget) -> None:
        super().__init__()
        self.stream = path.open("wb", buffering=0)
        self.budget = budget

    def writable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.stream.tell()

    def write(self, data: bytes) -> int:  # type: ignore[override]
        return self.budget.write(self.stream, data)

    def close(self) -> None:
        if not self.closed:
            self.stream.close()
        super().close()

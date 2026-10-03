"""Bounded sequential disk sorting of fixed-width SHA256 row digests."""

from collections.abc import Iterable, Iterator
from contextlib import ExitStack
from heapq import merge
from itertools import groupby
from pathlib import Path
from typing import BinaryIO

from pipeline.config.content import DigestLimits

WIDTH = 32


def read_hashes(stream: BinaryIO) -> Iterator[bytes]:
    while value := stream.read(WIDTH):
        if len(value) != WIDTH:
            raise ValueError("Truncated row-digest scratch file")
        yield value


class RowHashes:
    """Use small sorted runs and bounded merge fan-in, never random B-tree writes."""

    def __init__(self, root: Path, limits: DigestLimits) -> None:
        self.limits = limits
        self.root = root
        root.mkdir()
        self.pending: list[bytes] = []
        self.runs: list[Path] = []
        self.serial = 0

    def _path(self) -> Path:
        path = self.root / f"{self.serial}.bin"
        self.serial += 1
        return path

    def add(self, values: Iterable[bytes]) -> None:
        for value in values:
            if len(value) != WIDTH:
                raise ValueError("Expected a SHA256 row digest")
            self.pending.append(value)
            if len(self.pending) >= self.limits.chunk_rows:
                self._flush()

    def _flush(self) -> None:
        if self.pending:
            self.pending.sort()
            path = self._path()
            path.write_bytes(b"".join(self.pending))
            self.runs.append(path)
            self.pending.clear()

    @staticmethod
    def _merged(paths: list[Path]) -> Iterator[bytes]:
        with ExitStack() as stack:
            streams = [stack.enter_context(p.open("rb")) for p in paths]
            yield from merge(*(read_hashes(stream) for stream in streams))

    def counts(self) -> Iterator[tuple[bytes, int]]:
        self._flush()
        while len(self.runs) > self.limits.merge_fan_in:
            next_runs = []
            for start in range(0, len(self.runs), self.limits.merge_fan_in):
                batch = self.runs[start : start + self.limits.merge_fan_in]
                path = self._path()
                with path.open(
                    "wb", buffering=self.limits.write_buffer_bytes
                ) as stream:
                    stream.writelines(self._merged(batch))
                for old in batch:
                    old.unlink()
                next_runs.append(path)
            self.runs = next_runs
        for value, group in groupby(self._merged(self.runs)):
            if len(value) != WIDTH:
                raise ValueError("Truncated row-digest scratch file")
            yield value, sum(1 for _ in group)

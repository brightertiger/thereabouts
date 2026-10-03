"""Bounded sequential disk sorting of fixed-width SHA256 row digests."""

from collections.abc import Iterable, Iterator
from contextlib import ExitStack
from heapq import merge
from itertools import groupby
from pathlib import Path
from typing import BinaryIO

CHUNK_ROWS = 250_000
FAN_IN = 64
WIDTH = 32


def read_hashes(stream: BinaryIO) -> Iterator[bytes]:
    while value := stream.read(WIDTH):
        if len(value) != WIDTH:
            raise ValueError("Truncated row-digest scratch file")
        yield value


class RowHashes:
    """Use small sorted runs and bounded merge fan-in, never random B-tree writes."""

    def __init__(self, root: Path) -> None:
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
            if len(self.pending) >= CHUNK_ROWS:
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
        while len(self.runs) > FAN_IN:
            next_runs = []
            for start in range(0, len(self.runs), FAN_IN):
                batch = self.runs[start : start + FAN_IN]
                path = self._path()
                with path.open("wb", buffering=1024 * 1024) as stream:
                    stream.writelines(self._merged(batch))
                for old in batch:
                    old.unlink()
                next_runs.append(path)
            self.runs = next_runs
        for value, group in groupby(self._merged(self.runs)):
            if len(value) != WIDTH:
                raise ValueError("Truncated row-digest scratch file")
            yield value, sum(1 for _ in group)

"""Remember the bytes behind identities, and notice when they change mid-run."""

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

REPOSITORY = Path(__file__).parents[2]

Signature = tuple[int, int, int, int]


class InputsChanged(ValueError):
    """Hashed code or data changed after the run fixed its identities."""


def signature(path: Path) -> Signature:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino


def name(path: Path) -> str:
    return (
        path.relative_to(REPOSITORY).as_posix()
        if path.is_relative_to(REPOSITORY)
        else str(path)
    )


def changed_message(names: list[str]) -> str:
    return (
        f"Hashed inputs changed during the run: {', '.join(names)}. Units that "
        "finished after the change were not recorded; restart the run to use the "
        "edited files."
    )


@dataclass
class Entry:
    signature: Signature
    sha256: str
    payload: bytes | None


class Watch:
    """Every file read into an identity or parameter goes through one watch.

    Outside a run each read returns the current bytes. While a run holds the
    watch frozen, the first read of a file fixes its bytes for that run, a read
    that finds other bytes raises, and `changed()` reports edits at unit
    boundaries. Signatures avoid rehashing; a changed signature with the same
    bytes, such as a touch, is not a change.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.entries: dict[Path, Entry] = {}
        self.depth = 0

    @contextmanager
    def frozen(self) -> Iterator[None]:
        with self.lock:
            if not self.depth:
                # A new run starts from the files as they are now.
                self.entries.clear()
            self.depth += 1
        try:
            yield
        finally:
            with self.lock:
                self.depth -= 1

    def read(self, path: Path) -> bytes:
        payload = self._entry(path, keep=True).payload
        assert payload is not None
        return payload

    def digest(self, path: Path) -> str:
        return self._entry(path, keep=False).sha256

    def _entry(self, path: Path, *, keep: bool) -> Entry:
        path = path.absolute()
        with self.lock:
            known = self.entries.get(path)
            current = signature(path)
            if (
                self.depth
                and known is not None
                and known.signature == current
                and (known.payload is not None or not keep)
            ):
                return known
            payload = path.read_bytes()
            entry = Entry(
                current, hashlib.sha256(payload).hexdigest(), payload if keep else None
            )
            if self.depth and known is not None and known.sha256 != entry.sha256:
                raise InputsChanged(changed_message([name(path)]))
            self.entries[path] = entry
            return entry

    def changed(self) -> list[str]:
        with self.lock:
            entries = list(self.entries.items())
        result = []
        for path, entry in entries:
            try:
                current = signature(path)
            except FileNotFoundError:
                result.append(name(path))
                continue
            if current == entry.signature:
                continue
            with path.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            if sha != entry.sha256:
                result.append(name(path))
            else:
                with self.lock:
                    entry.signature = current
        return sorted(result)

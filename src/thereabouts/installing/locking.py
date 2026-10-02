"""Nonblocking per-family locks, released by the OS after a process exits."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import InstallationError


@contextmanager
def installation_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if sys.platform == "win32":
            import msvcrt

            stream.seek(0)
            if not stream.read(1):
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise InstallationError(
                    "Another reverse installation holds the lock"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise InstallationError(
                    "Another reverse installation holds the lock"
                ) from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)

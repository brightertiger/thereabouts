"""Small hashing and durable publication helpers."""

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path


def sha256_file(path: Path) -> str:
    """Hash a file without loading it into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(inputs: Mapping[str, object]) -> str:
    """Hash JSON inputs/parameters; callers include builder and policy versions."""
    encoded = json.dumps(
        inputs,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(temporary: Path, destination: Path) -> None:
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    sync_directory(destination.parent)


@contextmanager
def atomic_output(path: Path, validate: Callable[[Path], None]) -> Iterator[Path]:
    """Yield a sibling temporary; validate and durably replace on successful exit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=path.parent
    )
    os.close(fd)
    temporary = Path(name)
    try:
        yield temporary
        validate(temporary)
        publish(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: Mapping[str, object]) -> None:
    """Publish a JSON object durably after checking that it can be read back."""
    with atomic_output(
        path, lambda p: json.loads(p.read_text(encoding="utf-8"))
    ) as temp:
        temp.write_text(
            json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )

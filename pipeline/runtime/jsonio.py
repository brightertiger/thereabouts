"""Canonical JSON and atomic file publication with bounded file hashing."""

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeAlias, cast

from .paths import relative

JSON: TypeAlias = "bool | int | float | str | list[JSON] | dict[str, JSON] | None"
Object: TypeAlias = dict[str, JSON]


def encode(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(encode(value)).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_record(root: Path, path: Path) -> Object:
    """A root-relative path with the size and SHA-256 of its current bytes."""
    return {
        "path": relative(root, path),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def read_object(path: Path) -> Object:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return cast(Object, value)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def atomic_output(path: Path) -> Iterator[Path]:
    """Publish on successful exit; callers validate before leaving the context."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, suffix=".part")
    os.close(descriptor)
    temporary = Path(name)
    try:
        yield temporary
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    payload = encode(value) + b"\n"
    if path.is_file() and path.read_bytes() == payload:
        return
    with atomic_output(path) as temporary:
        temporary.write_bytes(payload)

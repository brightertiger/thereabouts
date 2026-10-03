"""Verify immutable objects by length and SHA256 before and after publication."""

import hashlib
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from fsspec.core import url_to_fs

from pipeline.runtime.jsonio import atomic_output


class Filesystem(Protocol):
    def open(self, path: str, mode: str) -> BinaryIO: ...
    def exists(self, path: str) -> bool: ...
    def makedirs(self, path: str, exist_ok: bool = False) -> None: ...
    def mv(self, source: str, target: str) -> None: ...
    def rm(self, path: str) -> None: ...


def backend(url: str) -> tuple[Filesystem, str]:
    fs, name = url_to_fs(url)
    return cast(Filesystem, fs), str(name)


def copy_stream(
    source: BinaryIO, target: BinaryIO, size: int, checksum: str, chunk_bytes: int
) -> None:
    digest = hashlib.sha256()
    copied = 0
    while block := source.read(chunk_bytes):
        copied += len(block)
        if copied > size:
            raise ValueError("Object exceeds its pinned size")
        digest.update(block)
        target.write(block)
    if copied != size or digest.hexdigest() != checksum:
        raise ValueError("Object does not match its pinned size and SHA256")


def verify(
    fs: Filesystem, name: str, size: int, checksum: str, chunk_bytes: int
) -> None:
    digest = hashlib.sha256()
    actual = 0
    with fs.open(name, "rb") as stream:
        while block := stream.read(chunk_bytes):
            actual += len(block)
            if actual > size:
                raise ValueError(f"Remote object exceeds pinned size: {name}")
            digest.update(block)
    if actual != size or digest.hexdigest() != checksum:
        raise ValueError(f"Remote object does not match pin: {name}")


def fetch(
    url: str, destination: Path, size: int, checksum: str, chunk_bytes: int
) -> None:
    fs, name = backend(url)
    with (
        atomic_output(destination) as temporary,
        fs.open(name, "rb") as source,
        temporary.open("wb") as target,
    ):
        copy_stream(source, target, size, checksum, chunk_bytes)


def mirror(path: Path, url: str, size: int, checksum: str, chunk_bytes: int) -> bool:
    fs, name = backend(url)
    if fs.exists(name):
        verify(fs, name, size, checksum, chunk_bytes)
        return False
    temporary = name + ".part." + uuid.uuid4().hex
    fs.makedirs(name.rpartition("/")[0], exist_ok=True)
    try:
        with path.open("rb") as source, fs.open(temporary, "wb") as target:
            copy_stream(source, target, size, checksum, chunk_bytes)
        verify(fs, temporary, size, checksum, chunk_bytes)
        if fs.exists(name):
            verify(fs, name, size, checksum, chunk_bytes)
        else:
            fs.mv(temporary, name)
            verify(fs, name, size, checksum, chunk_bytes)
    finally:
        if fs.exists(temporary):
            fs.rm(temporary)
    return True

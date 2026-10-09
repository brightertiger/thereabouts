"""Content-addressed mirror objects, vouched for by size and service checksums."""

import base64
import hashlib
import uuid
from contextlib import suppress
from functools import cached_property
from pathlib import Path
from typing import Any, BinaryIO, Protocol, cast

from fsspec.core import url_to_fs


class Filesystem(Protocol):
    def open(self, path: str, mode: str) -> BinaryIO: ...
    def exists(self, path: str) -> bool: ...
    def info(self, path: str) -> dict[str, Any]: ...
    def makedirs(self, path: str, exist_ok: bool = False) -> None: ...
    def mv(self, source: str, target: str) -> None: ...
    def rm(self, path: str) -> None: ...


def backend(url: str) -> tuple[Filesystem, str]:
    fs, name = url_to_fs(url)
    return cast(Filesystem, fs), str(name)


def address(sha256: str) -> str:
    return "sha256/" + sha256


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


class Local:
    """A verified local file; its checksums are computed once, when first needed."""

    def __init__(self, path: Path, size: int, sha256: str, chunk_bytes: int) -> None:
        self.path, self.size, self.sha256 = path, size, sha256
        self.chunk_bytes = chunk_bytes

    @cached_property
    def checksums(self) -> dict[str, bytes]:
        hashers: dict[str, Any] = {"md5Hash": hashlib.md5()}
        with suppress(ImportError):
            from google_crc32c import Checksum  # Installed with gcsfs.

            hashers["crc32c"] = Checksum()  # type: ignore[no-untyped-call]
        with self.path.open("rb") as stream:
            while block := stream.read(self.chunk_bytes):
                for hasher in hashers.values():
                    hasher.update(block)
        return {key: hasher.digest() for key, hasher in hashers.items()}

    def matches(self, fs: Filesystem, name: str) -> bool:
        """Compare a remote object with this file without reading the object.

        GCS records MD5 (only CRC32C for composite uploads); local and in-memory
        filesystems record neither, so there the size is the cheap evidence.
        """
        info = fs.info(name)
        if int(info.get("size", -1)) != self.size:
            return False
        recorded = {
            key: base64.b64decode(value)
            for key in ("md5Hash", "crc32c")
            if (value := info.get(key))
        }
        if not recorded:
            return True
        comparable = recorded.keys() & self.checksums.keys()
        if comparable:
            return all(recorded[key] == self.checksums[key] for key in comparable)
        try:
            verify(fs, name, self.size, self.sha256, self.chunk_bytes)
        except ValueError:
            return False
        return True


def mirror(path: Path, url: str, size: int, checksum: str, chunk_bytes: int) -> bool:
    """Publish a verified local file at `url`; False when it is already there."""
    fs, name = backend(url)
    local = Local(path, size, checksum, chunk_bytes)
    if fs.exists(name):
        if not local.matches(fs, name):
            raise ValueError(f"Remote object does not match pin: {name}")
        return False
    temporary = name + ".part." + uuid.uuid4().hex
    fs.makedirs(name.rpartition("/")[0], exist_ok=True)
    try:
        with path.open("rb") as source, fs.open(temporary, "wb") as target:
            copy_stream(source, target, size, checksum, chunk_bytes)
        if not local.matches(fs, temporary):
            raise ValueError(f"Remote object does not match pin: {temporary}")
        if not fs.exists(name):
            fs.mv(temporary, name)
        if not local.matches(fs, name):
            raise ValueError(f"Remote object does not match pin: {name}")
    finally:
        if fs.exists(temporary):
            fs.rm(temporary)
    return True

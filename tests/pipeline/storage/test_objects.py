"""Mirror objects are vouched for by size and backend checksums, not re-read."""

import base64
import hashlib
from pathlib import Path
from typing import Any, BinaryIO

import fsspec
import google_crc32c
import pytest

from pipeline.storage import objects
from pipeline.storage.objects import address, mirror

PAYLOAD = b"content-addressed mirror payload"
SHA = hashlib.sha256(PAYLOAD).hexdigest()


class ObjectStore:
    """An in-memory bucket that reports MD5 or CRC32C like GCS and counts reads."""

    def __init__(self, checksum: str) -> None:
        self.fs = fsspec.filesystem("memory")
        self.checksum = checksum
        self.reads: list[str] = []

    def open(self, path: str, mode: str) -> BinaryIO:
        if "r" in mode:
            self.reads.append(path)
        stream: BinaryIO = self.fs.open(path, mode)
        return stream

    def exists(self, path: str) -> bool:
        return bool(self.fs.exists(path))

    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        self.fs.makedirs(path, exist_ok=exist_ok)

    def mv(self, source: str, target: str) -> None:
        self.fs.mv(source, target)

    def rm(self, path: str) -> None:
        self.fs.rm(path)

    def info(self, path: str) -> dict[str, Any]:
        result = dict(self.fs.info(path))
        # The service computes these on its side; the client never reads them back.
        data = self.fs.cat_file(path)
        if self.checksum == "md5":
            result["md5Hash"] = base64.b64encode(hashlib.md5(data).digest()).decode()
        elif self.checksum == "crc32c":
            crc32c = google_crc32c.value(data)
            result["crc32c"] = base64.b64encode(crc32c.to_bytes(4, "big")).decode()
        return result

    def put(self, path: str, data: bytes) -> None:
        with self.fs.open(path, "wb") as stream:
            stream.write(data)


@pytest.fixture(params=["md5", "crc32c", "none"])
def store(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> ObjectStore:
    result = ObjectStore(request.param)
    monkeypatch.setattr(objects, "backend", lambda url: (result, url[len("gs:/") :]))
    return result


def local(tmp_path: Path) -> Path:
    path = tmp_path / "object"
    path.write_bytes(PAYLOAD)
    return path


def test_upload_is_checked_by_metadata_without_reading_it_back(
    tmp_path: Path, store: ObjectStore
) -> None:
    url = f"gs://{tmp_path.name}/raw/{address(SHA)}"
    assert mirror(local(tmp_path), url, len(PAYLOAD), SHA, 8) is True
    assert store.fs.cat_file(f"/{tmp_path.name}/raw/{address(SHA)}") == PAYLOAD
    assert store.reads == []
    assert not store.fs.glob(f"/{tmp_path.name}/raw/sha256/*.part.*")


def test_existing_object_is_vouched_for_without_streaming(
    tmp_path: Path, store: ObjectStore
) -> None:
    url = f"gs://{tmp_path.name}/raw/{address(SHA)}"
    store.put(url[len("gs:/") :], PAYLOAD)
    assert mirror(local(tmp_path), url, len(PAYLOAD), SHA, 8) is False
    assert store.reads == []


def test_existing_object_with_other_bytes_is_refused(
    tmp_path: Path, store: ObjectStore
) -> None:
    url = f"gs://{tmp_path.name}/raw/{address(SHA)}"
    store.put(url[len("gs:/") :], PAYLOAD[::-1])
    if store.checksum == "none":
        # Without service checksums only the size is cheap; equal sizes pass.
        assert mirror(local(tmp_path), url, len(PAYLOAD), SHA, 8) is False
        store.put(url[len("gs:/") :], PAYLOAD + b"!")
    with pytest.raises(ValueError, match="does not match"):
        mirror(local(tmp_path), url, len(PAYLOAD), SHA, 8)


def test_checksum_without_a_local_implementation_falls_back_to_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ObjectStore("crc32c")
    monkeypatch.setattr(objects, "backend", lambda url: (store, url[len("gs:/") :]))
    monkeypatch.setattr(
        objects.Local,
        "checksums",
        property(lambda self: {"md5Hash": hashlib.md5(PAYLOAD).digest()}),
    )
    url = f"gs://{tmp_path.name}/raw/{address(SHA)}"
    store.put(url[len("gs:/") :], PAYLOAD)
    assert mirror(local(tmp_path), url, len(PAYLOAD), SHA, 8) is False
    assert store.reads == [url[len("gs:/") :]]
    store.put(url[len("gs:/") :], PAYLOAD[::-1])
    with pytest.raises(ValueError, match="does not match"):
        mirror(local(tmp_path), url, len(PAYLOAD), SHA, 8)

"""Raw inputs are content-addressed objects restored with retries and resume."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, BinaryIO

import fsspec
import pytest

from pipeline.config.sources import Licence, SourceLimits, SourceSettings
from pipeline.pins.models import PinFile, SourcePin
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe
from pipeline.sources import download as module
from pipeline.sources.contract import SourceContext
from pipeline.sources.download import download, mirror_url
from pipeline.stages.contract import make_unit
from pipeline.storage import objects, transfer
from pipeline.storage.objects import backend

from ..helpers import context
from ..storage.flaky_server import Step, flaky


def pinned(url: str, payload: bytes, name: str = "airports.csv") -> PinFile:
    return PinFile(
        name,
        url,
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        metadata={"key": name},
    )


def source(root: Path, ledger: Ledger, *files: PinFile) -> SourceContext:
    ctx = context(root, ledger)
    ctx.storage = {"gcs_raw": "memory://objects-mirror/" + root.name}
    settings = SourceSettings(
        name="airports",
        adapter="pipeline.sources.airports",
        kind="airports",
        licence=Licence("Public-Domain", "https://example.test/licence", "Synthetic"),
        limits=SourceLimits(
            download_bytes=sum(item.size for item in files),
            retries=3,
            backoff_seconds=0.0,
            timeout_seconds=5.0,
        ),
    )
    pin = SourcePin("fixture", "2026-10-09", files=list(files))
    return SourceContext(
        ctx, settings, pin, make_unit(ctx, Recipe("download", "airports"), "fixture")
    )


def upload(url: str, payload: bytes) -> None:
    fs, name = backend(url)
    with fs.open(name, "wb") as stream:
        stream.write(payload)


def test_same_name_with_new_bytes_is_a_new_object(tmp_path: Path) -> None:
    url = "memory://objects-upstream/" + tmp_path.name + "/airports.csv"
    with Ledger(tmp_path, None, readonly=False) as ledger:
        upload(url, b"first release")
        first = source(tmp_path, ledger, pinned(url, b"first release"))
        old = download(first)[0]
        upload(url, b"second release, longer")
        second = source(tmp_path, ledger, pinned(url, b"second release, longer"))
        new = download(second)[0]
    assert old != new
    assert old.read_bytes() == b"first release"
    assert new.read_bytes() == b"second release, longer"
    assert new == tmp_path / "raw/airports/sha256" / second.pin.files[0].sha256
    inventory = json.loads((tmp_path / "raw/airports/inventory.json").read_bytes())
    assert inventory["files"]["airports.csv"]["path"] == (
        "raw/airports/sha256/" + second.pin.files[0].sha256
    )


def test_damaged_object_is_removed_and_restored(tmp_path: Path) -> None:
    url = "memory://objects-upstream/" + tmp_path.name + "/airports.csv"
    upload(url, b"pinned bytes")
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = source(tmp_path, ledger, pinned(url, b"pinned bytes"))
        path = download(ctx)[0]
        path.write_bytes(b"bit rot here")
        assert download(ctx)[0] == path
    assert path.read_bytes() == b"pinned bytes"


def test_names_pinning_identical_bytes_share_one_object(tmp_path: Path) -> None:
    url = "memory://objects-upstream/" + tmp_path.name + "/airports.csv"
    upload(url, b"same bytes")
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = source(
            tmp_path,
            ledger,
            pinned(url, b"same bytes", "a.csv"),
            pinned(url, b"same bytes", "b.csv"),
        )
        outputs = download(ctx)
        assert ctx.input("a.csv") == ctx.input("b.csv")
    assert len(outputs) == 2 and outputs[-1].name == "inventory.json"
    assert len(list((tmp_path / "raw/airports/sha256").iterdir())) == 1


def test_upstream_short_body_is_resumed_and_mirrored(tmp_path: Path) -> None:
    body = bytes(range(256)) * 64
    with flaky(body, [Step(cut=1000)]) as server:
        with Ledger(tmp_path, None, readonly=False) as ledger:
            pin = replace(pinned(server.url, body), etag=server.etag)
            ctx = source(tmp_path, ledger, pin)
            path = download(ctx)[0]
        assert server.ranges() == [None, "bytes=1000-"]
        assert all(h["If-Match"] == server.etag for _, h in server.requests)
    assert path.read_bytes() == body
    _, name = backend(mirror_url(ctx.runtime.storage["gcs_raw"], pin))
    assert fsspec.filesystem("memory").cat_file(name) == body


class FailingOnce:
    """Delegates to the in-memory filesystem after failing a chosen operation once."""

    def __init__(self, mode: str) -> None:
        self.fs = fsspec.filesystem("memory")
        self.mode = mode
        self.failures = 0

    def open(self, path: str, mode: str) -> BinaryIO:
        if mode == self.mode and not self.failures:
            self.failures += 1
            raise ConnectionResetError("object store connection reset")
        stream: BinaryIO = self.fs.open(path, mode)
        return stream

    def __getattr__(self, name: str) -> Any:
        return getattr(self.fs, name)


@pytest.mark.parametrize("mode", ["rb", "wb"])
def test_mirror_reads_and_writes_are_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    store = FailingOnce(mode)
    real = backend

    def patched(url: str) -> tuple[Any, str]:
        if url.startswith("gs://"):
            return store, url.removeprefix("gs:/")
        return real(url)

    for owner in (module, objects, transfer):
        monkeypatch.setattr(owner, "backend", patched)
    upstream = "memory://objects-upstream/" + tmp_path.name + "/airports.csv"
    upload(upstream, b"kept")
    bucket = "/bucket-" + tmp_path.name + "/raw"
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = source(tmp_path, ledger, pinned(upstream, b"kept"))
        ctx.runtime.storage["gcs_raw"] = "gs:/" + bucket
        stored = bucket + "/sha256/" + ctx.pin.files[0].sha256
        if mode == "rb":
            fsspec.filesystem("memory").rm(upstream.removeprefix("memory:/"))
            with store.fs.open(stored, "wb") as stream:
                stream.write(b"kept")
        assert download(ctx)[0].read_bytes() == b"kept"
    assert store.failures == 1
    assert store.fs.cat_file(stored) == b"kept"

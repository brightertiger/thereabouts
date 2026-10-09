"""Mirroring is part of completion and can restore bytes without upstream access."""

import hashlib
import importlib
import json
from pathlib import Path

import fsspec
import pyarrow.parquet as pq
import pytest

from pipeline.config.sources import Licence, SourceLimits, SourceSettings
from pipeline.pins.models import PinFile, SourcePin
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe
from pipeline.runtime.runner import run
from pipeline.sources import airports
from pipeline.sources.contract import SourceContext
from pipeline.sources.download import download, mirror_url
from pipeline.stages.contract import make_unit
from pipeline.stages.sources import adapter_context
from pipeline.storage.objects import backend

from ..helpers import context
from .fixtures import source_context


def fixture(
    root: Path, ledger: Ledger, payload: bytes, gcs_raw: str | None = None
) -> SourceContext:
    ctx = context(root, ledger)
    ctx.storage = {
        "local": "file://",
        "gcs_raw": gcs_raw or "memory://mirror/" + root.name,
    }
    url = "memory://upstream/" + root.name + "/airports.csv"
    fs, name = backend(url)
    with fs.open(name, "wb") as stream:
        stream.write(payload)
    sha = hashlib.sha256(payload).hexdigest()
    pin = PinFile(
        "airports.csv", url, len(payload), sha, metadata={"key": "airports.csv"}
    )
    selected = SourcePin(
        "fixture",
        "2026-10-03",
        files=[pin],
    )

    settings = SourceSettings(
        name="airports",
        adapter="pipeline.sources.airports",
        kind="airports",
        licence=Licence("Public-Domain", "https://example.test/licence", "Synthetic"),
        limits=SourceLimits(download_bytes=len(payload), retries=0, batch_rows=2),
    )
    return adapter_context(
        ctx,
        settings,
        selected,
        make_unit(ctx, Recipe("download", "airports"), "fixture"),
    )


def test_mirror_restores_missing_local_file_after_upstream_disappears(
    tmp_path: Path,
) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source = fixture(tmp_path, ledger, b"fixed source bytes")
        first = download(source)
        pin = source.pin.files[0]
        mirror = mirror_url(source.storage["gcs_raw"], pin)
        fs, key = backend(mirror)
        assert fs.exists(key)
        before = fsspec.filesystem("memory").info(key)["created"]
        download(source)
        assert fsspec.filesystem("memory").info(key)["created"] == before
        source.input(pin.name).unlink()
        upstream, name = backend(pin.url)
        upstream.rm(name)
        assert download(source) == first
        assert source.input(pin.name).read_bytes() == b"fixed source bytes"


def test_bad_source_bytes_publish_neither_payload_nor_inventory(tmp_path: Path) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source = fixture(tmp_path, ledger, b"pinned bytes")
        pin = source.pin.files[0]
        fs, name = backend(pin.url)
        with fs.open(name, "wb") as stream:
            stream.write(b"wrong")
        with pytest.raises(ValueError, match="pinned size"):
            download(source)
        assert not source.input(pin.name).exists()
        assert not (source.raw / "inventory.json").exists()


def test_airport_normalization_writes_only_relative_metadata(tmp_path: Path) -> None:
    payload = (
        b"ident,name,latitude_deg,longitude_deg,iso_country,type\n"
        b"TEST,Example,50.8,4.3,BE,small_airport\n"
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source = fixture(tmp_path, ledger, payload)
        download(source)
        outputs = airports.normalize(source)
        manifest = json.loads((source.normalized / "manifest.json").read_bytes())
        assert manifest["rows"] == {"airports": 1}
        assert str(tmp_path) not in json.dumps(manifest)
        partition = next(p for p in outputs if p.suffix == ".parquet")
        row = pq.read_table(partition).to_pylist()[0]
        assert row["ident"] == "TEST" and row["country_code"] == "BE"
        assert row["h3_resolution"] == 8


def test_mirror_failure_leaves_runner_unit_uncommitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        runtime, source, stages = source_context(
            tmp_path, ledger, "airports", {"airports.csv": (b"payload", {})}
        )
        module = importlib.import_module("pipeline.sources.download")

        def interrupted(*args: object, **kwargs: object) -> bool:
            raise OSError("mirror interrupted")

        with monkeypatch.context() as patch:
            patch.setattr(module, "mirror", interrupted)
            with pytest.raises(OSError, match="mirror interrupted"):
                run(runtime, stages[:1])
        assert ledger.get("download", "airports") is None
        assert source.input("airports.csv").read_bytes() == b"payload"
        assert run(runtime, stages[:1]) == {"completed": 1, "skipped": 0}


@pytest.mark.parametrize("directory", ["raw", "normalized", "work"])
def test_source_directory_cannot_escape_through_symlink(
    tmp_path: Path, directory: str
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / directory).mkdir()
    (root / directory / "airports").symlink_to(outside, target_is_directory=True)
    with Ledger(root, None, readonly=False) as ledger:
        source = fixture(root, ledger, b"small fixture")
        with pytest.raises(ValueError, match="symlink"):
            getattr(source, directory)
    assert list(outside.iterdir()) == []


def test_local_directory_mirror_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    with Ledger(root, None, readonly=False) as ledger:
        mirror = (tmp_path / "mirror").as_uri()
        source = fixture(root, ledger, b"local mirror fixture", mirror)
        download(source)
        pin = source.pin.files[0]
        mirrored = tmp_path / "mirror/sha256" / pin.sha256
        before = mirrored.stat().st_mtime_ns
        download(source)
        assert mirrored.read_bytes() == b"local mirror fixture"
        assert mirrored.stat().st_mtime_ns == before
        assert not list((tmp_path / "mirror").rglob("*.part.*"))

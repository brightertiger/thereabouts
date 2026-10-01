"""Lookup download pinning, local reuse and decompressed publisher checksums."""

import gzip
import hashlib
from pathlib import Path
from typing import Any

import pytest

from build_data.acquire import Workspace
from build_data.acquire import lookup_download as downloads
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import write_json
from build_data.acquire.status import source_status


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    w = Workspace(tmp_path)
    w.prepare()
    return w


def test_download_freezes_pins_and_hashes_decompressed_csv(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"8.8.8.0,8.8.8.255,NA,US,CA,Mountain View,37,-122\n"
    body = gzip.compress(content)
    name = "sample.csv.gz"
    specification = dict(
        url="https://example.invalid/file.gz",
        license="CC-BY",
        license_url="https://example.invalid/license",
        attribution="DB-IP",
        publisher_md5=hashlib.md5(content).hexdigest(),
    )
    monkeypatch.setattr(downloads, "catalog", lambda _: {name: specification})
    monkeypatch.setattr(
        downloads,
        "probe",
        lambda _: dict(
            size=len(body), etag='"test"', last_modified=None, retrieved_at="today"
        ),
    )
    calls: list[str] = []

    def transfer(url: str, destination: Path, **kwargs: Any) -> Path:
        calls.append(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        return destination

    monkeypatch.setattr(downloads, "download_file", transfer)
    downloads.download(workspace, "dbip")
    inventory = workspace.raw("dbip") / "inventory.json"
    before = inventory.read_bytes()
    downloads.download(workspace, "dbip")
    assert calls == [specification["url"]]
    assert inventory.read_bytes() == before
    assert source_status(workspace, "dbip")["download"] == "complete"


def test_failed_publisher_checksum_does_not_complete(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "sample.csv.gz"
    specification = dict(url="https://example.invalid/file.gz", publisher_md5="0" * 32)
    monkeypatch.setattr(downloads, "catalog", lambda _: {name: specification})
    body = gzip.compress(b"wrong")
    monkeypatch.setattr(
        downloads,
        "probe",
        lambda _: dict(size=len(body), etag='"test"', last_modified=None),
    )

    def transfer(url: str, destination: Path, **kwargs: Any) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        return destination

    monkeypatch.setattr(downloads, "download_file", transfer)
    with pytest.raises(ValueError, match="Publisher MD5"):
        downloads.download(workspace, "dbip")
    assert source_status(workspace, "dbip")["download"] == "incomplete"
    assert "completed_at" not in read_json(workspace.raw("dbip") / "inventory.json")


def test_local_country_reference_is_copied_without_modifying_geonames(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = workspace.raw("geonames") / "countryInfo.txt"
    existing.write_bytes(b"# local snapshot\n")
    original = existing.stat().st_mtime_ns
    write_json(
        existing.with_name("inventory.json"),
        {
            "files": {
                "countryInfo.txt": {
                    "path": str(existing),
                    "sha256": hashlib.sha256(existing.read_bytes()).hexdigest(),
                }
            }
        },
    )
    monkeypatch.setattr(
        downloads,
        "catalog",
        lambda _: {"countryInfo.txt": {"url": "https://example.invalid/countryInfo"}},
    )
    downloads.download(workspace, "codes")
    assert (
        workspace.raw("codes") / "snapshot/countryInfo.txt"
    ).read_bytes() == existing.read_bytes()
    assert existing.stat().st_mtime_ns == original

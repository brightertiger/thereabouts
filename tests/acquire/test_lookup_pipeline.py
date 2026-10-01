"""Synthetic source commits, rejection accounting, corruption and verified no-op."""

import zipfile
from pathlib import Path
from typing import Any

import pytest

from build_data.acquire import Ledger, Workspace, fingerprint, lookup_normalize
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import write_json
from build_data.acquire.lifecycle import resume_download
from build_data.acquire.lookup_normalize import normalize
from build_data.acquire.lookup_reader import records
from build_data.acquire.manifests import load_manifest
from build_data.acquire.status import source_status
from build_data.acquire.writer import PartitionWriter


@pytest.fixture
def postal_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    w = Workspace(tmp_path)
    w.prepare()
    archive = w.raw("postal") / "allCountries.zip"
    rows = [
        "IN\t560001\tBengaluru\tKarnataka\tKA\t\t\t\t\t12.97\t77.59\t6",
        "bad",
        "US\t10001\tNew York\tNew York\tNY\t\t\t\t\tNaN\t-74\t1",
    ]
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("allCountries.txt", "\n".join(rows) + "\n")
    pin = dict(
        path=str(archive),
        url="https://example.invalid/postal.zip",
        size=archive.stat().st_size,
        license="CC-BY-4.0",
        license_url="https://example.invalid/license",
        attribution="GeoNames",
        retrieved_at="today",
    )
    inventory = dict(
        source="postal",
        source_release="test",
        completed_at="today",
        specifications={"allCountries.zip": {}},
        files={"allCountries.zip": pin},
    )
    write_json(w.raw("postal") / "inventory.json", inventory)
    Ledger(w.ledger_path).complete(
        "postal.download", "allCountries.zip", fingerprint(pin), [archive]
    )
    return w


def test_normalization_reports_rejects_and_keeps_unlocated(
    postal_workspace: Workspace,
) -> None:
    normalize(postal_workspace, "postal")
    manifest = load_manifest(postal_workspace, "postal")
    assert manifest["rows"] == {"postal_codes": 2}
    report = read_json(postal_workspace.normalized("postal") / "verification.json")
    assert report["input_rows"] == 3 and report["rejects"] == 1
    assert report["invalid_coordinates"] == 1 and report["unlocated"] == 1
    assert source_status(postal_workspace, "postal")["normalize"] == "complete"
    assert source_status(postal_workspace, "postal")["download"] == "complete"


def test_rerun_does_no_work_and_corrupt_partition_is_rebuilt(
    postal_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    normalize(postal_workspace, "postal")
    manifest = load_manifest(postal_workspace, "postal")
    path = Path(manifest["partitions"][0]["path"])
    before = {
        p: p.stat().st_mtime_ns
        for p in postal_workspace.normalized("postal").rglob("*")
        if p.is_file()
    }
    reader = records

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("verified rerun must skip input parsing")

    monkeypatch.setattr(lookup_normalize, "records", fail)
    assert resume_download(postal_workspace, "postal")
    normalize(postal_workspace, "postal")
    assert before == {p: p.stat().st_mtime_ns for p in before}
    monkeypatch.setattr(lookup_normalize, "records", reader)
    path.write_bytes(b"corrupt")
    normalize(postal_workspace, "postal")
    assert load_manifest(postal_workspace, "postal")["rows"] == {"postal_codes": 2}


def test_writer_failure_is_not_a_rejected_record(
    postal_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("disk full")

    monkeypatch.setattr(PartitionWriter, "finish", fail)
    with pytest.raises(OSError, match="disk full"):
        normalize(postal_workspace, "postal")
    assert not (postal_workspace.normalized("postal") / "manifest.json").exists()

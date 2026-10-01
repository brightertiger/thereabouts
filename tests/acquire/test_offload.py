from __future__ import annotations

from typing import Any

import pytest

from build_data.acquire import Workspace, current_partitions
from build_data.acquire.__main__ import ADAPTERS, main
from build_data.acquire.manifests import load_manifest
from build_data.acquire.offload import offload, restore, state
from build_data.acquire.status import source_status
from tests.acquire.test_manifests import completed as fixture_completed

__all__ = ["fixture_completed"]


def test_offloaded_sources_verify_normalized_and_never_redownload(
    fixture_completed: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = fixture_completed.raw("overture") / "input.bin"
    original = raw.read_bytes()
    raw.unlink()
    offload(
        fixture_completed, "overture", "gs://bucket/raw/overture", record_existing=True
    )
    assert state(fixture_completed, "overture")
    assert source_status(fixture_completed, "overture")["download"] == "offloaded"
    assert current_partitions(fixture_completed, "overture", "places")

    def forbidden(workspace: Workspace) -> None:
        raise AssertionError("offloaded source dispatched")

    monkeypatch.setitem(ADAPTERS, "overture", (forbidden, forbidden))
    assert main(["overture", "--data-dir", str(fixture_completed.root)]) == 0
    calls = []

    def rsync(command: list[str], **kwargs: Any) -> None:
        calls.append(command)
        assert "--delete-unmatched-destination-objects" not in command
        raw.write_bytes(original)

    monkeypatch.setattr("build_data.acquire.offload.subprocess.run", rsync)
    restore(fixture_completed, "overture")
    assert calls[0][:4] == ["gcloud", "storage", "rsync", "--recursive"]
    assert not state(fixture_completed, "overture")
    assert raw.read_bytes() == original
    assert load_manifest(fixture_completed, "overture")


def test_offload_does_not_hide_corrupt_normalized_or_present_raw(
    fixture_completed: Workspace,
) -> None:
    offload(
        fixture_completed, "overture", "gs://bucket/raw/overture", record_existing=True
    )
    raw = fixture_completed.raw("overture") / "input.bin"
    raw.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="verification failed"):
        load_manifest(fixture_completed, "overture")
    raw.unlink()
    part = current_partitions(fixture_completed, "overture", "places")[0]
    part.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Unverified normalization"):
        load_manifest(fixture_completed, "overture")


def test_missing_restore_bytes_preserves_offload_marker(
    fixture_completed: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    offload(
        fixture_completed, "overture", "gs://bucket/raw/overture", record_existing=True
    )
    (fixture_completed.raw("overture") / "input.bin").unlink()
    monkeypatch.setattr(
        "build_data.acquire.offload.subprocess.run", lambda *a, **k: None
    )
    with pytest.raises(FileNotFoundError):
        restore(fixture_completed, "overture")
    assert state(fixture_completed, "overture")

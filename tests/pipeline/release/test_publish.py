"""Local/memory publication is idempotent, verifies bytes and commits success last."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import fsspec
import pytest

from pipeline.config.release import PublishSettings
from pipeline.release.publish import Upload, publish
from pipeline.runtime.jsonio import sha256_file


@pytest.mark.parametrize("backend", ["file", "memory"])
def test_dry_run_idempotence_and_conflicts(tmp_path: Path, backend: str) -> None:
    payload = tmp_path / "payload"
    payload.write_bytes(b"hello release")
    destination = (
        (tmp_path / "remote").as_uri()
        if backend == "file"
        else f"memory://release-{uuid4()}"
    )
    fs, base = fsspec.core.url_to_fs(destination)
    item = Upload(
        payload,
        "dataset/2026.10/data.bin",
        payload.stat().st_size,
        sha256_file(payload),
    )
    settings = PublishSettings()
    preview = publish([item], destination, "2026.10", settings, dry_run=True)
    assert preview["upload"] == 1 and not fs.exists(base)
    first = publish([item], destination, "2026.10", settings, dry_run=False)
    assert first["upload"] == 1
    marker = base + "/2026.10/_SUCCESS"
    assert fs.exists(marker)
    second = publish([item], destination, "2026.10", settings, dry_run=False)
    assert second["skip"] == 1 and second["upload"] == 0
    with fs.open(base + "/" + item.remote, "wb") as stream:
        stream.write(b"bad")
    with pytest.raises(ValueError, match="Conflicting"):
        publish([item], destination, "2026.10", settings, dry_run=False)


def test_failure_never_writes_success_and_retry_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = []
    for name in ("a", "b"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        files.append(Upload(path, f"dataset/2026.10/{name}", 1, sha256_file(path)))
    destination = f"memory://interrupted-{uuid4()}"
    fs, base = fsspec.core.url_to_fs(destination)
    original = fs.open
    writes = []

    def interrupted(path: str, mode: str = "rb", **kwargs: Any) -> Any:
        if mode == "wb":
            writes.append(path)
            if path.endswith("/b"):
                raise OSError("interrupted")
        return original(path, mode, **kwargs)

    monkeypatch.setattr(fs, "open", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        publish(files, destination, "2026.10", PublishSettings(), dry_run=False)
    assert not fs.exists(base + "/2026.10/_SUCCESS")
    assert not any(path.endswith("_SUCCESS") for path in writes)
    monkeypatch.setattr(fs, "open", original)
    result = publish(files, destination, "2026.10", PublishSettings(), dry_run=False)
    assert result["skip"] == 1 and result["upload"] == 1


def test_input_changes_during_upload_never_commit_success(tmp_path: Path) -> None:
    path = tmp_path / "payload"
    path.write_bytes(b"first")
    item = Upload(path, "dataset/2026.10/x", 5, sha256_file(path))
    path.write_bytes(b"other")
    destination = f"memory://changed-{uuid4()}"
    with pytest.raises(ValueError, match="checksum"):
        publish([item], destination, "2026.10", PublishSettings(), dry_run=False)
    fs, base = fsspec.core.url_to_fs(destination)
    assert not fs.exists(base + "/2026.10/_SUCCESS")

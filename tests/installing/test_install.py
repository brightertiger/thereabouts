import importlib
import shutil
from pathlib import Path
from typing import Any

import pytest

from thereabouts.client import Geocoder
from thereabouts.client_errors import InvalidInputError
from thereabouts.installing.errors import InstallationError
from thereabouts.installing.install import install
from thereabouts.installing.locking import installation_lock
from thereabouts.packs.errors import CorruptPackError
from thereabouts.packs.jsonio import canonical, digest, parse, sha256
from thereabouts.store import installed_pack, list_packs

from ..client.test_api import PACK

implementation = importlib.import_module("thereabouts.installing.install")


def release(target: Path) -> str:
    shutil.copytree(PACK, target)
    path = target / "manifest.json"
    value = parse(path.read_bytes())
    value["data_version"] = value["export"]["release"]["data_version"] = "second"
    value["export_fingerprint"] = digest(value["export"])
    path.write_bytes(canonical(value) + b"\n")
    return sha256(path)


def test_local_install_idempotence_discovery_and_retained_reader(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    pin = sha256(PACK / "manifest.json")
    assert list_packs(root) == []
    first = install(PACK, manifest_sha256=pin, data_dir=root, offline=True)
    stamps = {p: p.stat().st_mtime_ns for p in first.rglob("*") if p.is_file()}
    assert install(PACK, manifest_sha256=pin, data_dir=root) == first
    assert stamps == {p: p.stat().st_mtime_ns for p in stamps}
    assert installed_pack(root) == first
    with Geocoder(data_dir=root) as existing:
        expected = existing.reverse(12.97, 77.59)
        source = tmp_path / "second"
        pin2 = release(source)
        second = install(source, manifest_sha256=pin2, data_dir=root)
        assert second != first and first.is_dir()
        assert existing.reverse(12.97, 77.59) == expected
        with Geocoder(data_dir=root) as new:
            assert new.info()["packs"]["reverse"]["data_version"] == "second"
    records = list_packs(root)
    assert len(records) == 2 and sum(r["active"] for r in records) == 1
    assert next(r for r in records if r["active"])["version"] == "second"
    assert all(not Path(r["path"]).is_absolute() for r in records)


def test_failed_transfer_resumes_only_verified_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    pin = sha256(PACK / "manifest.json")
    transfer = implementation.transfer
    calls = []

    def interrupted(
        source: str | Path, name: str, target: Path, **options: Any
    ) -> None:
        calls.append(name)
        if len(calls) == 3:
            raise OSError("synthetic interruption")
        transfer(source, name, target, **options)

    monkeypatch.setattr(implementation, "transfer", interrupted)
    with pytest.raises(InstallationError, match="interruption"):
        install(PACK, manifest_sha256=pin, data_dir=root)
    assert not (root / "packs/reverse/current.json").exists()
    retained = root / "staging" / pin / calls[1]
    stamp = retained.stat().st_mtime_ns
    calls.clear()

    def record(source: str | Path, name: str, target: Path, **options: Any) -> None:
        calls.append(name)
        transfer(source, name, target, **options)

    monkeypatch.setattr(implementation, "transfer", record)
    result = install(PACK, manifest_sha256=pin, data_dir=root)
    assert "manifest.json" not in calls
    assert (
        result / retained.relative_to(root / "staging" / pin)
    ).stat().st_mtime_ns == stamp
    assert not list(root.rglob(".transfer-*"))


def test_failed_activation_keeps_previous_and_can_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    first = install(PACK, manifest_sha256=sha256(PACK / "manifest.json"), data_dir=root)
    source = tmp_path / "second"
    pin = release(source)
    activate = implementation._activate

    def fail(*args: object) -> None:
        raise OSError("activation interrupted")

    monkeypatch.setattr(implementation, "_activate", fail)
    with pytest.raises(InstallationError, match="activation"):
        install(source, manifest_sha256=pin, data_dir=root)
    assert installed_pack(root) == first
    monkeypatch.setattr(implementation, "_activate", activate)
    second = install(source, manifest_sha256=pin, data_dir=root)
    assert installed_pack(root) == second


def test_pins_corruption_and_lock_conflict(tmp_path: Path) -> None:
    root = tmp_path / "store"
    with pytest.raises(CorruptPackError, match="checksum"):
        install(PACK, manifest_sha256="0" * 64, data_dir=root)
    assert not (root / "packs/reverse/current.json").exists()
    with (
        installation_lock(root / "packs/reverse/install.lock"),
        pytest.raises(InstallationError, match="lock"),
    ):
        install(PACK, manifest_sha256=sha256(PACK / "manifest.json"), data_dir=root)
    first = install(PACK, manifest_sha256=sha256(PACK / "manifest.json"), data_dir=root)
    manifest = first / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(CorruptPackError, match="digest"):
        installed_pack(root)


@pytest.mark.parametrize(
    "bad", ["../escape", "/absolute", "a/../b", "manifest.json", "a\\b"]
)
def test_malicious_inventory_paths(tmp_path: Path, bad: str) -> None:
    source = tmp_path / "source"
    shutil.copytree(PACK, source)
    path = source / "manifest.json"
    value = parse(path.read_bytes())
    value["files"][0]["path"] = bad
    path.write_bytes(canonical(value))
    with pytest.raises(CorruptPackError):
        install(source, manifest_sha256=sha256(path), data_dir=tmp_path / "store")
    assert not (tmp_path / "escape").exists()


def test_invalid_options_and_disk_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin = sha256(PACK / "manifest.json")
    with pytest.raises(InvalidInputError):
        install(PACK, manifest_sha256="not a digest", data_dir=tmp_path)
    with pytest.raises(InvalidInputError):
        install(PACK, manifest_sha256=pin, data_dir=tmp_path, timeout=0)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        implementation.shutil, "disk_usage", lambda _: usage._replace(free=0)
    )
    with pytest.raises(InstallationError, match="disk"):
        install(PACK, manifest_sha256=pin, data_dir=tmp_path)


def test_symlink_source_and_store_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(PACK, source)
    manifest = parse((source / "manifest.json").read_bytes())
    name = manifest["files"][0]["path"]
    (source / name).unlink()
    (source / name).symlink_to((PACK / name).resolve())
    with pytest.raises(CorruptPackError, match="path"):
        install(
            source,
            manifest_sha256=sha256(source / "manifest.json"),
            data_dir=tmp_path / "store",
        )
    outside = tmp_path / "unmanaged"
    outside.mkdir()
    root = tmp_path / "unsafe"
    root.mkdir()
    (root / "packs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CorruptPackError, match="path"):
        install(PACK, manifest_sha256=sha256(PACK / "manifest.json"), data_dir=root)
    assert list(outside.iterdir()) == []

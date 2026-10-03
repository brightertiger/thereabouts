"""Current store pins and native platform paths preserve Python discovery."""

import json
import shutil
from importlib import import_module
from pathlib import Path

import pytest

from thereabouts import Geocoder, IncompatibleDataError, _core
from thereabouts.store import active_pack, data_directory
from thereabouts.store_files import sha256

PACKS = Path(__file__).parents[1] / "fixtures/packs"


def test_native_default_matches_platformdirs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THEREABOUTS_DATA", raising=False)
    import sys

    name = "Thereabouts" if sys.platform in ("darwin", "win32") else "thereabouts"
    # Compare the native path policy with the Python platformdirs implementation.
    platformdirs = import_module("platformdirs")
    expected = Path(platformdirs.user_data_dir(name, appauthor=False))
    assert data_directory() == expected
    assert Path(_core.data_directory()) == expected


def test_one_pin_controls_all_families(tmp_path: Path) -> None:
    pin: dict[str, object] = {"data_version": "2026.10", "packs": {}}
    pointers = {}
    for family in ("core", "postal"):
        source = PACKS / f"{family}-sample"
        info = _core.pack_info(str(source))
        pin["data_version"] = info["data_version"]
        path = tmp_path / "packs" / family / info["data_version"]
        shutil.copytree(source, path)
        pointers[family] = {
            "path": path.relative_to(tmp_path).as_posix(),
            "manifest_sha256": sha256(path / "manifest.json"),
        }
    pin["packs"] = pointers
    (tmp_path / "active.json").write_text(json.dumps(pin))
    with Geocoder(data_dir=tmp_path) as geo:
        assert geo.reverse(lat=48.8566, lon=2.3522).status == "matched"
        assert geo.postal("75001", country="FR").status == "matched"
    assert active_pack(tmp_path) == tmp_path / pointers["core"]["path"]
    pin["data_version"] = "different"
    (tmp_path / "active.json").write_text(json.dumps(pin))
    from thereabouts import CorruptPackError

    with pytest.raises(CorruptPackError, match="identity mismatch"):
        Geocoder(data_dir=tmp_path)


def test_legacy_reverse_diagnosis_survives_native_discovery(tmp_path: Path) -> None:
    pointer = tmp_path / "packs/reverse/current.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("{}")
    with pytest.raises(IncompatibleDataError, match="Legacy reverse"):
        Geocoder(data_dir=tmp_path)


@pytest.mark.parametrize(
    ("platform", "module", "class_name", "name"),
    [
        ("macos", "macos", "MacOS", "Thereabouts"),
        ("linux", "unix", "Unix", "thereabouts"),
        ("windows", "windows", "Windows", "Thereabouts"),
    ],
)
def test_each_platform_matches_platformdirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    platform: str,
    module: str,
    class_name: str,
    name: str,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    policy = import_module(f"platformdirs.{module}")
    if platform == "windows":
        # Exercise path assembly on other hosts using the environment resolver.
        monkeypatch.setattr(
            policy, "get_win_folder", policy.get_win_folder_from_env_vars
        )
    expected = getattr(policy, class_name)(name, appauthor=False).user_data_dir
    assert Path(_core.platform_directory(platform)) == Path(expected)


def test_missing_directory_environment_has_coded_discovery_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from thereabouts import DataNotInstalledError

    for key in ("HOME", "LOCALAPPDATA", "XDG_DATA_HOME", "THEREABOUTS_DATA"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(
        DataNotInstalledError, match="thereabouts data install core"
    ) as exc:
        data_directory()
    assert exc.value.code == "data_not_installed"

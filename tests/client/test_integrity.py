import shutil
from pathlib import Path

import pytest

from thereabouts.client import Geocoder
from thereabouts.errors import DataNotInstalledError
from thereabouts.packs.errors import CorruptPackError, UnsupportedPackError
from thereabouts.packs.jsonio import canonical, parse

from .test_api import PACK, ROOT, finest


def test_missing_and_unsupported_pack(tmp_path: Path) -> None:
    with pytest.raises(DataNotInstalledError):
        Geocoder(tmp_path / "absent")
    target = tmp_path / "pack"
    shutil.copytree(PACK, target)
    manifest = target / "manifest.json"
    value = parse(manifest.read_bytes())
    value["format"]["major"] = 2
    manifest.write_bytes(canonical(value))
    with pytest.raises(UnsupportedPackError):
        Geocoder(target)


def test_corruption_fails_operation_even_with_collect(tmp_path: Path) -> None:
    target = tmp_path / "pack"
    shutil.copytree(PACK, target)
    value = parse((target / "manifest.json").read_bytes())
    for record in value["files"]:
        if record["kind"] == "cells":
            path = target / record["path"]
            content = path.read_bytes()
            path.write_bytes(b"badmagic" + content[8:])
    with Geocoder(target) as geo, pytest.raises(CorruptPackError):
        list(geo.from_h3_many([finest(ROOT)], errors="collect"))
    with pytest.raises(CorruptPackError, match="Checksum"):
        Geocoder(target, verify=True)


def test_mixed_release_rejected(tmp_path: Path) -> None:
    target = tmp_path / "pack"
    shutil.copytree(PACK, target)
    path = target / "manifest.json"
    value = parse(path.read_bytes())
    value["catalogue_epoch"] = "different"
    path.write_bytes(canonical(value))
    with pytest.raises(CorruptPackError, match="release"):
        Geocoder(target)

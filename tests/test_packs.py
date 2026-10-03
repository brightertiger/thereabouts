"""Mmap structure errors, checksums and runtime dependency isolation."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from thereabouts import DamagedPackError, Geocoder, UnsupportedSchemaError

from .conftest import FIXTURE


@pytest.fixture
def copy_pack(tmp_path: Path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "pack"))


@pytest.mark.parametrize("damage", ["manifest", "size", "missing", "layout"])
def test_damaged_pack(copy_pack: Path, damage: str) -> None:
    manifest = copy_pack / "manifest.json"
    if damage == "manifest":
        manifest.write_text("{")
    elif damage == "layout":
        value = json.loads(manifest.read_text())
        value["layout"] = "mystery"
        manifest.write_text(json.dumps(value))
    else:
        file = copy_pack / "combined-keys.bin"
        if damage == "missing":
            file.unlink()
        else:
            file.write_bytes(b"broken")
    with pytest.raises(DamagedPackError):
        Geocoder(copy_pack)


def test_unsupported_schema(copy_pack: Path) -> None:
    manifest = copy_pack / "manifest.json"
    value = json.loads(manifest.read_text())
    value["schema_version"] = "future"
    manifest.write_text(json.dumps(value))
    with pytest.raises(UnsupportedSchemaError):
        Geocoder(copy_pack)


def test_runtime_never_imports_build_dependencies() -> None:
    code = """
import sys
from thereabouts import Geocoder
with Geocoder(sys.argv[1]) as geocoder:
    assert geocoder.reverse(52.37, 4.9)
for name in sys.modules:
    assert name.split('.')[0] not in {'shapely', 'scipy', 'build_data'}
"""
    subprocess.run([sys.executable, "-c", code, str(FIXTURE)], check=True)


def test_full_verification_and_checksum_damage(copy_pack: Path) -> None:
    from tests.support.verify import verify

    verify(copy_pack)
    file = copy_pack / "combined-values.bin"
    value = bytearray(file.read_bytes())
    value[0] ^= 1
    file.write_bytes(value)
    with pytest.raises(DamagedPackError, match="checksum"):
        verify(copy_pack)

import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pyofflinegeocoder import (
    ClosedGeocoderError,
    DamagedPackError,
    DataNotInstalledError,
    Geocoder,
    UnsupportedSchemaError,
)

from .conftest import FIXTURE


@pytest.fixture
def copy_pack(tmp_path: Path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "pack"))


def rewrite_manifest(path: Path, key: str, value: Any) -> None:
    manifest = path / "manifest.json"
    content = json.loads(manifest.read_text())
    content[key] = value
    manifest.write_text(json.dumps(content))


def test_missing_pack_has_explicit_build_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYOFFLINEGEOCODER_DATA", raising=False)
    for path in (None, tmp_path / "missing"):
        with pytest.raises(DataNotInstalledError, match="python -m build_data"):
            Geocoder(path)


def test_environment_selects_pack_and_explicit_path_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYOFFLINEGEOCODER_DATA", str(FIXTURE))
    with Geocoder() as geocoder:
        assert geocoder.reverse(50, 5).country.status == "matched"
    monkeypatch.setenv("PYOFFLINEGEOCODER_DATA", "/not-installed")
    with Geocoder(FIXTURE) as geocoder:
        assert geocoder.info().schema_version == "1"


def test_close_is_idempotent_operations_fail_and_new_instance_reopens() -> None:
    geocoder = Geocoder(FIXTURE)
    expected = geocoder.reverse(50, 5)
    geocoder.close()
    geocoder.close()
    for operation in (
        lambda: geocoder.reverse(50, 5),
        geocoder.info,
        geocoder.verify,
        lambda: list(geocoder.reverse_many([])),
        geocoder.__enter__,
    ):
        with pytest.raises(ClosedGeocoderError):
            operation()
    with Geocoder(FIXTURE) as reopened:
        assert reopened.reverse(50, 5) == expected
        reopened.verify()


def test_iterator_stops_with_closed_error_after_close() -> None:
    geocoder = Geocoder(FIXTURE)
    results = geocoder.reverse_many([(50, 5), (51, 5)])
    next(results)
    geocoder.close()
    with pytest.raises(ClosedGeocoderError):
        next(results)


def test_unsupported_schema_is_distinct(copy_pack: Path) -> None:
    rewrite_manifest(copy_pack, "schema_version", "999")
    with pytest.raises(UnsupportedSchemaError):
        Geocoder(copy_pack)


@pytest.mark.parametrize(
    "kind",
    [
        "missing_manifest",
        "bad_json",
        "truncated",
        "missing_array",
        "offsets",
        "dtype",
        "object_array",
        "text_reference",
    ],
)
def test_damaged_pack_structure_is_rejected_on_open(copy_pack: Path, kind: str) -> None:
    if kind == "missing_manifest":
        (copy_pack / "manifest.json").unlink()
    elif kind == "bad_json":
        (copy_pack / "manifest.json").write_text("{")
    elif kind == "missing_array":
        (copy_pack / "places.npy").unlink()
    elif kind == "truncated":
        with (copy_pack / "country_wkb.npy").open("r+b") as stream:
            stream.truncate(300)
    elif kind == "offsets":
        array = np.load(copy_pack / "country_offsets.npy", mmap_mode="r+")
        array[1] = len(np.load(copy_pack / "country_wkb.npy")) + 1
        array.flush()
    elif kind == "text_reference":
        array = np.load(copy_pack / "places.npy", mmap_mode="r+")
        array["name"][0] = 2**32 - 1
        array.flush()
    else:
        target = copy_pack / "country_wkb.npy"
        if kind == "object_array":
            with target.open("wb") as stream:
                header = b"{'descr': '|O', 'fortran_order': False, 'shape': (1,), }"
                header = header.ljust(117) + b"\n"
                stream.write(
                    b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header
                )
        else:
            np.save(target, np.zeros(20, dtype="f8"), allow_pickle=False)
        manifest = json.loads((copy_pack / "manifest.json").read_text())
        manifest["files"][target.name]["size"] = target.stat().st_size
        (copy_pack / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(DamagedPackError):
        Geocoder(copy_pack)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sources", [None]),
        ("coverage_bbox", [0, 1]),
        ("coverage_bbox", [False, 1, 2, 3]),
        ("policy_id", "unknown"),
        ("files", {}),
        ("snapshot_id", 123),
    ],
)
def test_malformed_manifest_is_a_damaged_pack(
    copy_pack: Path, field: str, value: Any
) -> None:
    rewrite_manifest(copy_pack, field, value)
    with pytest.raises(DamagedPackError):
        Geocoder(copy_pack)


def test_invalid_utf8_and_wkb_are_detected_when_decoded(copy_pack: Path) -> None:
    blob = np.load(copy_pack / "text.npy", mmap_mode="r+")
    blob[:] = 255
    blob.flush()
    with (
        Geocoder(copy_pack) as geocoder,
        pytest.raises(DamagedPackError, match="UTF-8"),
    ):
        geocoder.reverse(50, 5)


def test_invalid_wkb_is_detected_on_first_query(copy_pack: Path) -> None:
    blob = np.load(copy_pack / "country_wkb.npy", mmap_mode="r+")
    blob[:5] = 255
    blob.flush()
    with (
        Geocoder(copy_pack) as geocoder,
        pytest.raises(DamagedPackError, match="geometry"),
    ):
        geocoder.reverse(50, 5)


def test_content_damage_requires_full_checksum_verification(copy_pack: Path) -> None:
    blob = np.load(copy_pack / "text.npy", mmap_mode="r+")
    blob[0] = ord("X")
    blob.flush()
    with (
        Geocoder(copy_pack) as geocoder,
        pytest.raises(DamagedPackError, match="checksum"),
    ):
        geocoder.verify()


def test_import_does_not_touch_data_or_network_and_default_is_lazy() -> None:
    script = """
import os, sys
from pathlib import Path
path = Path(os.environ["PYOFFLINEGEOCODER_DATA"]).resolve()
def audit(event, args):
    if event.startswith("socket."):
        raise AssertionError("network access")
    if event == "open" and isinstance(args[0], (str, bytes)):
        if str(path) in os.fsdecode(args[0]):
            raise AssertionError("pack accessed on import")
sys.addaudithook(audit)
import pyofflinegeocoder
print("imported")
"""
    environment = {**os.environ, "PYOFFLINEGEOCODER_DATA": str(FIXTURE.resolve())}
    output = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.stdout.strip() == "imported"


def test_process_local_default_and_spawned_process_can_query() -> None:
    script = (
        "from pyofflinegeocoder import reverse; "
        "print(reverse(50, 5).country.value.code)"
    )
    environment = {**os.environ, "PYOFFLINEGEOCODER_DATA": str(FIXTURE.resolve())}
    output = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.stdout.strip() == "BE"

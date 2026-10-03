"""Malformed payloads fail after checksums are refreshed, testing the decoder too."""

from pathlib import Path
from struct import pack_into
from typing import Any

import pytest

from pipeline.engines.serving.checkpoints import file_record
from pipeline.engines.serving.metadata import write_manifest
from thereabouts.packs.catalogue import Catalogue
from thereabouts.packs.errors import CorruptPackError, UnsupportedPackError
from thereabouts.packs.jsonio import parse
from thereabouts.packs.layout import HEADER, KEYS, PLACES, TEXT, VALUES
from thereabouts.packs.spatial import Spatial
from thereabouts.packs.verify import verify


def payload(pack: Path, kind: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
    value = parse((pack / "manifest.json").read_bytes())
    record = next(r for r in value["files"] if r["kind"] == kind)
    return value, record, pack / record["path"]


def rehash(
    pack: Path, value: dict[str, Any], record: dict[str, Any], path: Path
) -> None:
    record.update(file_record(path, pack))
    write_manifest(pack / "manifest.json", value)


@pytest.mark.parametrize(
    "case", ["magic", "major", "features", "length", "span", "sections"]
)
def test_invalid_container_header(serving: Path, case: str) -> None:
    value, record, path = payload(serving, "cells")
    data = bytearray(path.read_bytes())
    if case == "magic":
        data[0] = 0
    elif case == "major":
        pack_into("<H", data, 8, 99)
    elif case == "features":
        pack_into("<I", data, 12, 1)
    elif case == "length":
        pack_into("<Q", data, 24, len(data) + 8)
    elif case == "span":
        pack_into("<Q", data, HEADER.size + 8, 2**64 - 1)
    else:
        pack_into("<I", data, 20, 2**32 - 1)
    path.write_bytes(data)
    rehash(serving, value, record, path)
    error = UnsupportedPackError if case in {"major", "features"} else CorruptPackError
    with pytest.raises(error):
        verify(serving)


@pytest.mark.parametrize("case", ["reference", "method_null", "flags", "key"])
def test_invalid_cell_payload(serving: Path, case: str) -> None:
    value, record, path = payload(serving, "cells")
    spatial = Spatial(path, value["place_count"])
    try:
        row = next(iter(spatial.blocks.values()))
        assert row.count == 1 and row.width == 0
        label = spatial.sections[VALUES].offset + row.values
        key = spatial.sections[KEYS].offset + row.keys
    finally:
        spatial.close()
    data = bytearray(path.read_bytes())
    if case == "reference":
        pack_into("<I", data, label, value["place_count"] + 1)
    elif case == "method_null":
        pack_into("<I", data, label + 12, 0)
    elif case == "flags":
        pack_into("<I", data, label + 12, 64)
    else:
        pack_into("<H", data, key, 65535)
    path.write_bytes(data)
    rehash(serving, value, record, path)
    with pytest.raises(CorruptPackError):
        verify(serving)


@pytest.mark.parametrize(
    "case", ["utf8", "text_reference", "place_reference", "checksum"]
)
def test_invalid_catalogue(serving: Path, case: str) -> None:
    value, record, path = payload(serving, "catalogue")
    catalogue = Catalogue(path, value["place_count"])
    text, place = catalogue.sections[TEXT].offset, catalogue.sections[PLACES].offset
    catalogue.close()
    data = bytearray(path.read_bytes())
    if case in {"utf8", "checksum"}:
        data[text] = 255
    elif case == "text_reference":
        pack_into("<I", data, place, 2**32 - 1)
    else:
        pack_into("<I", data, place + 48, value["place_count"] + 1)
    path.write_bytes(data)
    if case != "checksum":
        rehash(serving, value, record, path)
    with pytest.raises(CorruptPackError):
        verify(serving)


@pytest.mark.parametrize(
    "case",
    ["traversal", "absolute", "duplicate", "world", "epoch", "boolean", "symlink"],
)
def test_manifest_rejects_mismatches(serving: Path, case: str) -> None:
    value, record, path = payload(serving, "catalogue")
    if case == "traversal":
        record["path"] = "../" + record["path"]
    elif case == "absolute":
        record["path"] = str(path.resolve())
    elif case == "duplicate":
        value["files"].append(record)
    elif case == "world":
        value["coverage"] = "world"
    elif case == "epoch":
        value["catalogue_epoch"] = "other"
    elif case == "boolean":
        value["format"]["major"] = True
    else:
        target = path.with_suffix(".real")
        path.rename(target)
        path.symlink_to(target.name)
    write_manifest(serving / "manifest.json", value)
    with pytest.raises(CorruptPackError):
        verify(serving)

import shutil
import zlib
from pathlib import Path
from typing import Any

import pytest

from pipeline.engines.serving_codes.encoding import Buffer
from thereabouts.client import Geocoder
from thereabouts.packs.errors import CorruptPackError
from thereabouts.packs.exact import Exact
from thereabouts.packs.jsonio import canonical, parse, sha256
from thereabouts.packs.layout import CODE_INDEX, KEY_RECORD
from thereabouts.packs.verify import verify


def copy_pack(source: Path, target: Path) -> tuple[dict[str, Any], Path]:
    shutil.copytree(source, target)
    value = parse((target / "manifest.json").read_bytes())
    record = next(row for row in value["files"] if row["kind"] == "exact")
    return record, target / record["path"]


def test_decompression_bound_and_trailing_stream_are_rejected(
    code_packs: dict[str, Path], tmp_path: Path
) -> None:
    record, path = copy_pack(code_packs["postal"], tmp_path / "bound")
    shard = Exact(path, int(record["max_record_bytes"]))
    offset, fields = shard.sections[CODE_INDEX].offset, list(shard.record(0))
    shard.close()
    data = bytearray(path.read_bytes())
    fields[-1] = int(record["max_record_bytes"]) + 1
    KEY_RECORD.pack_into(data, offset, *fields)
    path.write_bytes(data)
    with pytest.raises(CorruptPackError, match="spans"):
        Exact(path, int(record["max_record_bytes"]))

    raw = canonical({"candidates": [None]})
    buffer = Buffer()
    buffer.add("AA\0X", 1, raw, zlib.compress(raw) + b"trailing")
    malformed = tmp_path / "trailing.bin"
    buffer.write(malformed)
    shard = Exact(malformed, len(raw))
    try:
        with pytest.raises(CorruptPackError, match="framing"):
            shard.payload(0)
    finally:
        shard.close()


def test_bad_references_fail_full_verification(
    code_packs: dict[str, Path], tmp_path: Path
) -> None:
    target = tmp_path / "bad"
    shutil.copytree(code_packs["postal"], target)
    value = parse((target / "manifest.json").read_bytes())
    record = next(row for row in value["files"] if row["kind"] == "exact")
    path = target / record["path"]
    shard = Exact(path, record["max_record_bytes"])
    buffer = Buffer()
    try:
        for i in range(shard.count):
            body = shard.payload(i)
            body["candidates"][0]["refs"][0] = value["place_count"] + 1
            raw = canonical(body)
            buffer.add(
                shard.key(i).decode(), len(body["candidates"]), raw, zlib.compress(raw)
            )
    finally:
        shard.close()
    buffer.write(path)
    record.update(
        size=path.stat().st_size, sha256=sha256(path), max_record_bytes=buffer.maximum
    )
    (target / "manifest.json").write_bytes(canonical(value))
    with pytest.raises(CorruptPackError, match="reference"):
        verify(target)
    with Geocoder(target) as geo, pytest.raises(CorruptPackError, match="reference"):
        geo.postal("00100", country="AA")

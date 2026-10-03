"""Subdivision rows supply public state names; absent rows use place fields."""

import json
import shutil
import struct
from pathlib import Path

from thereabouts import Geocoder

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_state_metadata_precedes_place_name_and_falls_back(tmp_path: Path) -> None:
    target = tmp_path / "pack"
    shutil.copytree(FIXTURES / "packs/core-synthetic", target)
    path = target / "metadata.bin"
    original = path.read_bytes()
    offset, length = struct.unpack_from("<QQ", original, 40)
    metadata = json.loads(original[offset : offset + length])
    for subdivisions, expected in [
        (
            [{"code": "AA.A", "name": "Published subdivision", "country_code": "AA"}],
            "Published subdivision",
        ),
        ([], "München 東京 state:synthetic:A"),
    ]:
        metadata["subdivisions"] = subdivisions
        payload = json.dumps(metadata).encode()
        data = bytearray(original[:offset]) + payload
        struct.pack_into("<Q", data, 24, len(data))
        struct.pack_into("<QQ", data, 48, len(payload), len(payload))
        path.write_bytes(data)
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        next(row for row in manifest["files"] if row["kind"] == "metadata")["size"] = (
            len(data)
        )
        manifest_path.write_text(json.dumps(manifest))
        with Geocoder(target) as geo:
            result = geo.from_h3("8860140001fffff")
            assert result.state is not None
            assert result.state.code == "AA.A"
            assert result.state.name == expected

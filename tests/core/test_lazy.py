"""Lazy opening validates directories; accessing payloads validates their structure."""

import shutil
import struct
from pathlib import Path

import pytest

from thereabouts import CorruptPackError, Geocoder, _core

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_lazy_payload_validation_and_explicit_verification(tmp_path: Path) -> None:
    target = tmp_path / "pack"
    shutil.copytree(FIXTURES / "packs/core-synthetic", target)
    shard = max(target.glob("cells-*.bin"), key=lambda path: path.stat().st_size)
    data = bytearray(shard.read_bytes())
    key_offset = struct.unpack_from("<Q", data, 72)[0]
    struct.pack_into("<H", data, key_offset, 65535)  # Outside every logical block.
    shard.write_bytes(data)
    with Geocoder(target):
        pass  # The directory is intact and unused payloads have not been read.
    with pytest.raises(CorruptPackError):
        _core.verify_pack(str(target))
    with pytest.raises(CorruptPackError):
        Geocoder(target, verify=True)
    # Find a coordinate in the corrupted block without depending on file ordering.
    block = struct.unpack_from("<I", data, 160)[0]
    import h3

    from tools.fixture_cells import cell_at

    cell = cell_at(block, 0)
    with Geocoder(target) as geo, pytest.raises(CorruptPackError):
        geo.from_h3(h3.int_to_str(cell))

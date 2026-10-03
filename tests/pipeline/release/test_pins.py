"""An old snapshot cannot accidentally claim a newly updated lock."""

from dataclasses import asdict
from pathlib import Path

import pytest

from pipeline.engines.artifact_io import file_record
from pipeline.pins.models import PinFile, SourcePin
from pipeline.release.pins import verify
from pipeline.runtime.jsonio import write_json


def test_release_pins_are_bound_to_built_inventory(tmp_path: Path) -> None:
    raw = tmp_path / "raw/sample"
    raw.mkdir(parents=True)
    (raw / "input").write_bytes(b"input")
    record = file_record(tmp_path, raw / "input")
    pin = SourcePin(
        "2026-10",
        "2026-10-03",
        files=[
            PinFile("input", "http://localhost/input", record["size"], record["sha256"])
        ],
    )
    inventory = raw / "inventory.json"
    write_json(
        inventory,
        {
            "source_release": pin.release,
            "pinned_at": pin.pinned_at,
            "pin_metadata": pin.metadata,
            "files": {"input": {**asdict(pin.files[0]), "path": record["path"]}},
        },
    )
    manifest = tmp_path / "normalized/sample/manifest.json"
    write_json(
        manifest,
        {
            "source": "sample",
            "inventory": file_record(tmp_path, inventory),
            "inputs": [record],
        },
    )
    verify(tmp_path, "normalized", {"sample": pin})
    pin.release = "2026-11"
    with pytest.raises(ValueError, match="differs from built input"):
        verify(tmp_path, "normalized", {"sample": pin})
    manifest.unlink()
    with pytest.raises(ValueError, match="evidence is missing"):
        verify(tmp_path, "normalized", {"sample": pin})

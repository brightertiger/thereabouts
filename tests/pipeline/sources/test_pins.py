"""Lock updates are deliberate, portable and tied to recorded source evidence."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from pipeline.cli import main
from pipeline.config import load
from pipeline.pins.lock import read_lock, write_lock
from pipeline.pins.models import PinFile, SourcePin
from pipeline.pins.workspace import from_manifest
from pipeline.runtime.jsonio import digest, sha256_file, write_json


def test_lock_requires_explicit_update_and_rejects_unknown_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pins.lock"
    assert main(["pins", "update", "--lock", str(path)]) == 2
    assert not path.exists()
    original = SourcePin(
        "release",
        "2026-10-03",
        files=[PinFile("input.zip", "memory://input", 1, "a" * 64)],
    )
    proposal = tmp_path / "proposal.yaml"
    write_lock(proposal, {"example": original})
    assert (
        main(["pins", "update", "--lock", str(path), "--from-file", str(proposal)]) == 0
    )
    assert read_lock(path) == {"example": original}
    assert main(["pins", "check", "--lock", str(path)]) == 0
    bad = {"example": {**asdict(original), "releaze": "typo"}}
    proposal.write_text(yaml.safe_dump(bad))
    before = path.read_bytes()
    assert (
        main(["pins", "update", "--lock", str(path), "--from-file", str(proposal)]) == 2
    )
    assert path.read_bytes() == before


def test_workspace_pin_uses_manifest_inventory_and_bound_mirror_custody(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    inventory_path = root / "raw/example/frozen-inventory.json"
    inventory = {
        "source_release": "used-release",
        "retrieved_at": "2026-10-03",
        "files": {
            "input.zip": {
                "path": str(root / "raw/example/input.zip"),
                "url": "https://example.test/input.zip",
                "size": 42,
                "sha256": "a" * 64,
            }
        },
    }
    write_json(inventory_path, inventory)
    manifest = {
        "source": "example",
        "source_release": "used-release",
        "inventory": {
            "path": str(inventory_path),
            "size": inventory_path.stat().st_size,
            "sha256": sha256_file(inventory_path),
        },
        "inputs": [
            {
                "path": str(root / "raw/example/input.zip"),
                "size": 42,
                "sha256": "a" * 64,
            }
        ],
    }
    write_json(
        root / "raw/example/inventory.json", {"source_release": "newer-unused-release"}
    )
    custody = root / "work/offloaded/example.json"
    write_json(
        custody,
        {
            "offloaded": True,
            "manifest_sha256": digest(manifest),
            "remote": "memory://retained/example",
            "verification": "synthetic",
        },
    )
    pin = from_manifest(root, manifest)
    assert pin.release == "used-release"
    assert pin.metadata["mirror_base"] == "memory://retained/example"
    assert str(root) not in json.dumps(asdict(pin))
    assert pin.files[0].name == "input.zip"
    write_json(
        custody,
        {
            "offloaded": True,
            "manifest_sha256": "different",
            "remote": "memory://retained/example",
        },
    )
    with pytest.raises(ValueError, match="custody does not bind"):
        from_manifest(root, manifest)


@pytest.mark.parametrize(
    "override",
    [
        "sources.airports.limits.batch_rows=several",
        "sources.airports.limits.bach_rows=1",
        "sources.ghsl.options.expected_rows=0",
        "sources.geonames.options.line_byte=100",
    ],
)
def test_source_option_errors_precede_workspace_creation(
    tmp_path: Path, override: str
) -> None:
    root = tmp_path / "never-created"
    assert main(["run", "--root", str(root), override]) == 2
    assert not root.exists()


def test_overrides_and_cached_config_are_independent() -> None:
    config = load(overrides=["sources.airports.limits.batch_rows=2"])
    assert config.sources["airports"].limits.batch_rows == 2
    config.sources["airports"].limits.batch_rows = 999
    assert (
        load(overrides=["sources.airports.limits.batch_rows=2"])
        .sources["airports"]
        .limits.batch_rows
        == 2
    )

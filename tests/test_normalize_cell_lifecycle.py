"""Explicit base checkpoints and local activation preserve reproducible dependencies."""

from pathlib import Path

import pytest

from build_data.acquire import Workspace
from build_data.acquire.artifacts import file_record, read_json
from build_data.acquire.io import write_json
from build_data.golden.cells import builder
from build_data.golden.inputs import Inputs
from build_data.normalize_cells.base import load, snapshot
from build_data.normalize_cells.publish import activate


def test_base_snapshot_survives_original_directory_move(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    inputs = Inputs({}, {}, {}, {}, "reconciliation")
    source = tmp_path / "golden"
    source.mkdir()
    table = source / "table.parquet"
    table.write_bytes(b"verified test artifact")
    original = {
        "schema_version": "golden-1",
        "completed": True,
        "inputs": {
            "identity": inputs.identity,
            "countries": {},
            "golden_builder": builder(),
        },
        "tables": [{**file_record(table), "kind": "cells", "rows": 1}],
    }
    write_json(source / "manifest.json", original)
    path = snapshot(workspace, source / "manifest.json", inputs)
    assert snapshot(workspace, source / "manifest.json", inputs) == path
    source.rename(tmp_path / "retained")
    _, base = load(workspace, inputs)
    assert Path(base["tables"][0]["path"]).read_bytes() == b"verified test artifact"
    Path(base["tables"][0]["path"]).write_bytes(b"corruption")
    with pytest.raises(ValueError, match="size mismatch"):
        load(workspace, inputs)


def test_activation_retains_v1_and_stable_v2_paths(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    old = tmp_path / "golden"
    old.mkdir()
    table = old / "cells.parquet"
    table.write_bytes(b"old data")
    write_json(old / "manifest.json", {"tables": [file_record(table)]})
    new = tmp_path / "golden-v2"
    new.mkdir()
    artifact = new / "cells.parquet"
    artifact.write_bytes(b"new data")
    write_json(
        new / "manifest.json",
        {
            "completed": True,
            "schema_version": "golden-2",
            "tables": [file_record(artifact)],
            "verification_artifacts": [],
        },
    )
    activate(workspace, new)
    activate(workspace, new)
    assert old.is_symlink() and old.resolve() == new
    previous = read_json(tmp_path / "golden-v1/manifest.json")
    assert Path(previous["tables"][0]["path"]).read_bytes() == b"old data"
    assert (tmp_path / "golden-v1/manifest.original.json").exists()

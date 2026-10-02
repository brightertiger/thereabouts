"""Moving code/data preserves rebuilt guards without bypassing corruption checks."""

import shutil
from pathlib import Path

import pytest

from build_data.acquire import Workspace
from build_data.acquire.artifacts import file_record, read_json
from build_data.acquire.io import write_json
from build_data.acquire.ledger import Ledger as SourceLedger
from build_data.acquire.ledger import read_units
from build_data.golden import cells, paths
from build_data.golden.inputs import Inputs
from build_data.golden.ledger import Ledger, units
from build_data.normalize_cells import base, run
from build_data.normalize_cells.verify import verify
from build_data.rebuild_stages import completed_base
from build_data.reconcile.common import Row


def test_code_guards_ignore_checkout_location_but_detect_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path(__file__).parents[2]
    target = tmp_path / "another-checkout"
    for name in ("build_data", "src"):
        shutil.copytree(
            source / name, target / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    before = cells.builder(), run.implementation()
    monkeypatch.setattr(cells, "__file__", str(target / "build_data/golden/cells.py"))
    monkeypatch.setattr(
        run, "__file__", str(target / "build_data/normalize_cells/run.py")
    )
    assert (cells.builder(), run.implementation()) == before
    path = target / "build_data/golden/paths.py"
    path.write_text(path.read_text() + "\n# Changed implementation\n")
    assert cells.builder() != before[0]
    assert run.implementation() != before[1]
    modified = run.implementation()
    policy = target / "build_data/cities/policy.json"
    policy.write_text(policy.read_text() + "\n")
    assert run.implementation() != modified


def test_relative_ledger_survives_move_and_checks_bytes(tmp_path: Path) -> None:
    original = tmp_path / "old"
    original.mkdir()
    artifact = original / "golden/cells.parquet"
    artifact.parent.mkdir()
    artifact.write_bytes(b"good")
    workspace = Workspace(original)
    record = file_record(artifact)
    digest = paths.digest({"table": record}, original)
    ledger = Ledger(workspace)
    ledger.complete(
        "golden.cells", "block", digest, [artifact], metadata={"table": record}
    )
    raw = read_units(workspace.ledger_path, "golden.cells")[0]
    assert raw["outputs"][0]["path"] == "golden/cells.parquet"
    assert raw["metadata"]["table"]["path"] == "golden/cells.parquet"
    # The source ledger retains its current representation and fingerprints.
    SourceLedger(workspace.ledger_path).complete(
        "geonames.normalize", "unit", digest, [artifact]
    )
    upstream = read_units(workspace.ledger_path, "geonames.normalize")[0]
    assert upstream["outputs"][0]["path"] == str(artifact)
    moved = tmp_path / "new"
    original.rename(moved)
    workspace = Workspace(moved)
    record = units(workspace, "golden.cells")[0]["metadata"]["table"]
    assert paths.digest({"table": record}, moved) == digest
    ledger = Ledger(workspace)
    assert ledger.is_complete("golden.cells", "block", digest)
    (moved / "golden/cells.parquet").write_bytes(b"evil")
    assert not ledger.is_complete("golden.cells", "block", digest)
    with pytest.raises(ValueError, match="only for rebuilt"):
        ledger.complete("cities.country", "country", digest, [])


def test_snapshot_moves_and_stale_builder_regenerates_without_restamping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "data"
    source = original / "golden"
    source.mkdir(parents=True)
    artifact = source / "cells.parquet"
    artifact.write_bytes(b"rows")
    inputs = Inputs({}, {}, {}, {}, "source-code")
    value: Row = {
        "schema_version": "golden-1",
        "completed": True,
        "inputs": {
            "identity": inputs.identity,
            "countries": {},
            "golden_builder": cells.builder(),
        },
        "tables": [{**file_record(artifact), "kind": "cells", "rows": 1}],
    }
    write_json(source / "manifest.json", value)
    workspace = Workspace(original)
    old_snapshot = base.snapshot(workspace, source / "manifest.json", inputs)
    old_bytes = old_snapshot.read_bytes()
    relative_snapshot = old_snapshot.relative_to(original)
    moved = tmp_path / "moved"
    original.rename(moved)
    workspace = Workspace(moved)
    assert base.load(workspace, inputs)[0] == moved / relative_snapshot
    # A new builder returns control to the normal pipeline, preserving old hashes.
    monkeypatch.setattr(base, "builder", lambda: "new-builder")
    assert completed_base(workspace, inputs) is None
    assert (moved / relative_snapshot).read_bytes() == old_bytes
    value["inputs"]["golden_builder"] = "new-builder"
    value["tables"][0]["path"] = str(moved / "golden/cells.parquet")
    write_json(moved / "golden/manifest.json", value)
    rebuilt_snapshot = completed_base(workspace, inputs)
    assert (
        rebuilt_snapshot is not None and rebuilt_snapshot != moved / relative_snapshot
    )
    assert (moved / relative_snapshot).read_bytes() == old_bytes
    # Corruption is not a stale-code signal and must still fail visibly.
    pointer = paths.read(moved / "base_cells/current.json", moved)
    Path(pointer["manifest"]["path"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="size mismatch"):
        completed_base(workspace, inputs)


def test_completed_normalized_manifest_verifies_after_data_move(tmp_path: Path) -> None:
    original = tmp_path / "data"
    output = original / "golden-v2"
    output.mkdir(parents=True)
    artifact = output / "cells.parquet"
    artifact.write_bytes(b"good")
    value = {
        "schema_version": "golden-2",
        "data_root": "..",
        "completed": True,
        "implementation": run.implementation(),
        "tables": [file_record(artifact)],
        "verification_artifacts": [],
    }
    paths.write(output / "manifest.json", value, original)
    assert (
        read_json(output / "manifest.json")["tables"][0]["path"]
        == "golden-v2/cells.parquet"
    )
    relocated = tmp_path / "relocated"
    original.rename(relocated)
    verify(Workspace(relocated), relocated / "golden-v2")
    (relocated / "golden-v2/cells.parquet").write_bytes(b"evil")
    with pytest.raises(ValueError, match="verification failed"):
        verify(Workspace(relocated), relocated / "golden-v2")

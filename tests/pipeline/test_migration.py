"""Migration proves old hashes, works after a move, and never rebuilds data."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from pipeline.config import load
from pipeline.migration.adoption import simulate
from pipeline.migration.apply import apply
from pipeline.runtime.jsonio import digest, read_object, write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import plan
from pipeline.stages.registry import registry

from .helpers import legacy_workspace


def test_adoption_is_readonly_until_applied_and_portable(tmp_path: Path) -> None:
    root = tmp_path / "original"
    path = legacy_workspace(root)
    before = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    config = load()
    stages = registry(config)
    with Ledger(root, path) as old:
        migration = simulate(root, old, config, stages)
        try:
            assert migration.report["legacy_rows"] == 3
            assert migration.report["adopted_units"] == 2
            assert all(d.state == "current" for d in migration.decisions)
            assert before == {
                p.relative_to(root): p.read_bytes()
                for p in root.rglob("*")
                if p.is_file()
            }
            apply(migration, old, path)
        finally:
            migration.context.ledger.close()
    with sqlite3.connect(root / "work/ledger.pre-migration.sqlite3") as backup:
        assert backup.execute("SELECT count(*) FROM units").fetchone()[0] == 3
        assert (
            backup.execute(
                "SELECT count(*) FROM units WHERE stage='ghsl.download'"
            ).fetchone()[0]
            == 1
        )
    moved = tmp_path / "moved"
    shutil.move(str(root), moved)
    with Ledger(moved, moved / "work/ledger.sqlite3") as ledger:
        from .helpers import context

        assert all(d.state == "current" for d in plan(context(moved, ledger), stages))
        assert all(
            not o.path.startswith("/") for r in ledger.records() for o in r.outputs
        )
    manifest = read_object(moved / "normalized/ghsl/manifest.json")
    assert str(moved) not in json.dumps(manifest)
    assert str(root) not in json.dumps(manifest)


@pytest.mark.parametrize("corrupt", [False, True])
def test_adoption_cannot_bless_missing_or_corrupt_payload(
    tmp_path: Path, corrupt: bool
) -> None:
    path = legacy_workspace(tmp_path / "data")
    part = tmp_path / "data/normalized/ghsl/areas/part.parquet"
    if corrupt:
        part.write_bytes(b"corrupted parquet bytes")
    else:
        part.unlink()
    with (
        Ledger(path.parents[1], path) as ledger,
        pytest.raises(ValueError, match="Cannot adopt"),
    ):
        simulate(path.parents[1], ledger, load(), registry(load()))


def test_offloaded_missing_raw_keeps_evidence_but_claims_no_remote_verification(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    path = legacy_workspace(root)
    manifest = read_object(root / "normalized/ghsl/manifest.json")
    write_json(
        root / "work/offloaded/ghsl.json",
        {
            "source": "ghsl",
            "offloaded": True,
            "manifest_sha256": digest(manifest),
            "remote": "memory://raw/ghsl",
            "verification": "operator count and bytes",
        },
    )
    (root / "raw/ghsl/input.zip").unlink()
    with Ledger(root, path) as ledger:
        migration = simulate(root, ledger, load(), registry(load()))
        try:
            assert migration.report["offloaded_sources"] == ["ghsl"]
            assert migration.report["remote_verified"] is False
            assert migration.report["outputs_absent_units"] == 1
            assert all(d.state == "current" for d in migration.decisions)
        finally:
            migration.context.ledger.close()


def test_changed_offload_binding_does_not_authorize_absence(tmp_path: Path) -> None:
    root = tmp_path / "data"
    path = legacy_workspace(root)
    write_json(
        root / "work/offloaded/ghsl.json",
        {
            "source": "ghsl",
            "offloaded": True,
            "manifest_sha256": "different snapshot",
        },
    )
    with Ledger(root, path) as ledger, pytest.raises(ValueError, match="does not bind"):
        simulate(root, ledger, load(), registry(load()))

"""Consumers, interrupted publication and pruning share one verified commit."""

from pathlib import Path
from typing import Any

import pytest

from build_data.acquire import Ledger, Workspace, current_partitions, fingerprint
from build_data.acquire.__main__ import main
from build_data.acquire.artifacts import publish_report, read_json
from build_data.acquire.io import write_json
from build_data.acquire.lifecycle import finish_source, prune_source, resume_source
from build_data.acquire.manifests import load_manifest
from build_data.acquire.runtime import single_run
from build_data.acquire.status import source_status
from build_data.acquire.writer import PartitionWriter
from tests.acquire.test_schemas import example


@pytest.fixture
def completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    workspace = Workspace(tmp_path)
    workspace.prepare()
    raw = workspace.raw("overture") / "input.bin"
    raw.write_bytes(b"verified upstream input")
    write_json(
        raw.with_name("inventory.json"),
        {"source_release": "release", "objects": [{"key": "object"}]},
    )
    ledger = Ledger(workspace.ledger_path)
    ledger.complete("overture.download", "object", fingerprint({"raw": 1}), [raw])
    units = []
    for kind in ("areas", "places", "names"):
        digest = fingerprint({"kind": kind})
        writer = PartitionWriter(workspace, "overture", kind, kind, digest)
        writer.add(example(kind).to_pylist()[0])
        outputs = writer.finish()
        ledger.complete(
            "overture.normalize",
            kind,
            digest,
            outputs,
            metadata={"output_rows": {kind: 1}},
        )
        units.append(
            {"stage": "overture.normalize", "unit_id": kind, "inputs_hash": digest}
        )
    report = publish_report(
        workspace, "overture", {"rows": {"areas": 1, "places": 1, "names": 1}}
    )
    with single_run(workspace, "overture"):
        finish_source(workspace, "overture", "release", units, [report], {"policy": 1})
    return workspace


def test_consumer_ignores_orphans_and_prune_preserves_raw_and_reports(
    completed: Workspace,
) -> None:
    (area,) = current_partitions(completed, "overture", "areas")
    orphan = area.with_name("abandoned.parquet")
    orphan.write_bytes(b"partial failed attempt")
    work = completed.work / "overture"
    work.mkdir(exist_ok=True)
    temporary = work / "entities.sqlite3"
    temporary.write_bytes(b"old lookup")
    report = work / "verification.json"
    report.write_text("{}")
    log = work / "run.log"
    log.write_text("retain")
    assert current_partitions(completed, "overture", "areas") == (area,)
    with single_run(completed, "overture"):
        prune_source(completed, "overture")
    assert not orphan.exists() and not temporary.exists()
    assert report.exists() and log.exists()
    assert (
        completed.raw("overture") / "input.bin"
    ).read_bytes() == b"verified upstream input"


@pytest.mark.parametrize(
    "damage", ["output", "inventory", "manifest", "report", "ledger"]
)
def test_unverified_manifest_cannot_prune(completed: Workspace, damage: str) -> None:
    manifest = load_manifest(completed, "overture")
    orphan = completed.normalized("overture") / "orphan.parquet"
    orphan.write_bytes(b"preserve until verified")
    if damage == "output":
        Path(manifest["partitions"][0]["path"]).write_bytes(b"bad")
    elif damage == "inventory":
        write_json(
            completed.raw("overture") / "inventory.json", {"source_release": "changed"}
        )
    elif damage == "manifest":
        # Omitting an entire unit must not authorize deletion of its valid files.
        manifest["units"].pop()
        manifest["partitions"].pop()
        write_json(completed.normalized("overture") / "manifest.json", manifest)
    elif damage == "report":
        Path(manifest["auxiliary"][0]["path"]).write_text("corrupt")
    else:
        unit = manifest["units"][0]
        Ledger(completed.ledger_path).complete(
            unit["stage"], unit["unit_id"], "f" * 64, []
        )
    with pytest.raises((OSError, ValueError)):
        prune_source(completed, "overture")
    assert orphan.exists()
    with pytest.raises((OSError, ValueError)):
        current_partitions(completed, "overture", "areas")


def test_failed_manifest_publication_retains_previous_commit(
    completed: Workspace,
) -> None:
    path = completed.normalized("overture") / "manifest.json"
    old = path.read_bytes()
    units: list[dict[str, Any]] = read_json(path)["units"]
    units.append(
        {
            "stage": "overture.normalize",
            "unit_id": "uncommitted",
            "inputs_hash": "f" * 64,
        }
    )
    with pytest.raises(ValueError, match="Unverified normalization"):
        finish_source(completed, "overture", "release", units, [], {"policy": 1})
    assert path.read_bytes() == old
    assert load_manifest(completed, "overture")["rows"] == {
        "areas": 1,
        "places": 1,
        "names": 1,
    }


def test_resume_and_status_do_not_rewrite_verified_files(
    completed: Workspace, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {
        p: (p.stat().st_size, p.stat().st_mtime_ns)
        for p in completed.root.rglob("*")
        if p.is_file() and not p.name.endswith((".sqlite3-wal", ".sqlite3-shm"))
    }
    assert resume_source(completed, "overture", {"policy": 1})
    assert not resume_source(completed, "overture", {"policy": 2})
    assert main(["status", "--data-dir", str(completed.root)]) == 0
    assert "1 areas, 1 places, 1 names" in capsys.readouterr().out
    assert source_status(completed, "overture")["normalize"] == "complete"
    after = {
        p: (p.stat().st_size, p.stat().st_mtime_ns)
        for p in completed.root.rglob("*")
        if p.is_file() and not p.name.endswith((".sqlite3-wal", ".sqlite3-shm"))
    }
    assert after == before


def test_status_of_empty_workspace_is_read_only(tmp_path: Path) -> None:
    root = tmp_path / "absent"
    assert main(["status", "--data-dir", str(root)]) == 0
    assert not root.exists()

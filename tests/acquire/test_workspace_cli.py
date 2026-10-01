"""Disk limits, deterministic paths and repeatable CLI dispatch."""

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from build_data.acquire import Ledger, Workspace, atomic_output, fingerprint
from build_data.acquire.__main__ import ADAPTERS, main
from build_data.acquire.workspace import MIN_FREE_BYTES


def test_paths_and_reserve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = Workspace(tmp_path / "data")
    workspace.prepare()
    assert workspace.raw("osm_land") == workspace.root / "raw/osm_land"
    assert workspace.normalized("geonames") == workspace.root / "normalized/geonames"
    assert workspace.ledger_path == workspace.work / "ledger.sqlite3"
    first = workspace.partition("overture", "areas", "unsafe/unit", "0" * 64)
    assert first != workspace.partition("overture", "areas", "unsafe/unit", "1" * 64)
    assert first != workspace.partition("overture", "areas", "unsafe/unit", "0" * 64, 1)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        shutil, "disk_usage", lambda p: usage._replace(free=MIN_FREE_BYTES - 1)
    )
    with pytest.raises(OSError, match="12 GB"):
        workspace.check_budget()
    monkeypatch.setattr(
        shutil, "disk_usage", lambda p: usage._replace(free=MIN_FREE_BYTES)
    )
    workspace.check_budget()
    with pytest.raises(OSError, match="12 GB"):
        workspace.check_budget(required_bytes=1)
    with pytest.raises(ValueError):
        workspace.raw("../escape")


def test_workspace_hard_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from build_data.acquire import workspace as module

    workspace = Workspace(tmp_path)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        shutil, "disk_usage", lambda p: usage._replace(free=100_000_000_000)
    )
    monkeypatch.setattr(module, "MAX_WORKSPACE_BYTES", 4)
    (tmp_path / "some-data").write_bytes(b"12345")
    with pytest.raises(OSError, match="60 GB"):
        workspace.check_budget()


def test_budget_scan_tolerates_other_source_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(tmp_path)
    (tmp_path / "disappearing.part").write_bytes(b"temporary")
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(
        shutil, "disk_usage", lambda p: usage._replace(free=100_000_000_000)
    )
    original = Path.lstat

    def renamed(path: Path) -> os.stat_result:
        if path.name == "disappearing.part":
            raise FileNotFoundError("renamed by another source")
        return original(path)

    monkeypatch.setattr(Path, "lstat", renamed)
    workspace.check_budget()


def test_cli_twice_skips_all_completed_work_and_dispatches_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worked: list[str] = []
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)

    def adapter(source: str, stage: str) -> Callable[[Workspace], None]:
        def run(workspace: Workspace) -> None:
            ledger = Ledger(workspace.ledger_path)
            name = source + "." + stage
            key = fingerprint({"source": source, "stage": stage, "builder": 1})
            if ledger.is_complete(name, "unit", key):
                return
            workspace.check_budget()
            output = workspace.work / f"{name}.json"
            with atomic_output(output, lambda p: json.loads(p.read_text())) as temp:
                temp.write_text("{}")
            ledger.complete(name, "unit", key, [output])
            worked.append(name)

        return run

    for source in ADAPTERS:
        monkeypatch.setitem(
            ADAPTERS,
            source,
            (adapter(source, "download"), adapter(source, "normalize")),
        )
    args = ["all", "--data-dir", str(tmp_path)]
    assert main([*args, "--stage", "download"]) == 0
    assert worked == [source + ".download" for source in ADAPTERS]
    assert main(args) == 0
    assert len(worked) == 8
    assert main(args) == 0
    assert main(["geonames", "--stage", "normalize", "--data-dir", str(tmp_path)]) == 0
    assert len(worked) == 8


def test_adapter_failure_does_not_claim_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)

    def fail(workspace: Workspace) -> None:
        raise OSError("synthetic download failure")

    monkeypatch.setitem(ADAPTERS, "osm_land", (fail, fail))
    with pytest.raises(OSError, match="synthetic download failure"):
        main(["osm_land", "--data-dir", str(tmp_path)])
    assert not (tmp_path / "work/ledger.sqlite3").exists()


def test_cli_budget_refuses_to_start_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(self: Workspace, required_bytes: int = 0) -> None:
        raise OSError("Disk budget")

    monkeypatch.setattr(Workspace, "check_budget", blocked)
    with pytest.raises(OSError, match="Disk budget"):
        main(["osm_land", "--data-dir", str(tmp_path)])

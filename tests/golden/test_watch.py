from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pytest

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import write_json
from build_data.golden import __main__ as cli
from build_data.golden.storage import DiskBudgetExceeded


def test_watch_retries_disk_pause_without_claiming_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def cycle(workspace: Workspace, args: argparse.Namespace) -> bool:
        calls.append(True)
        if len(calls) == 1:
            write_json(workspace.work / "golden/run.json", {"built_blocks": 20})
            raise DiskBudgetExceeded("disk full")
        return True

    def sleep(seconds: float) -> None:
        state = read_json(tmp_path / "work/golden/run.json")
        assert state["built_blocks"] == 20
        assert state["stage"] == "waiting for disk"
        assert state["completed"] is False

    monkeypatch.setattr(cli, "cycle", cycle)
    monkeypatch.setattr(time, "sleep", sleep)
    monkeypatch.setattr(
        sys, "argv", ["golden", "run", "--watch", "--data-dir", str(tmp_path)]
    )
    cli.main()
    assert len(calls) == 2


def test_watch_does_not_swallow_other_io_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cycle(workspace: Workspace, args: argparse.Namespace) -> bool:
        raise OSError("bad read")

    monkeypatch.setattr(cli, "cycle", cycle)
    monkeypatch.setattr(
        sys, "argv", ["golden", "run", "--watch", "--data-dir", str(tmp_path)]
    )
    with pytest.raises(OSError, match="bad read"):
        cli.main()

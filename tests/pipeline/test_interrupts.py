"""Interrupts and failures keep finished work; destructive commands confirm."""

import json
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pipeline import arguments
from pipeline.cli import main
from pipeline.config import load
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe
from pipeline.runtime.runner import run
from pipeline.stages.contract import Context, Unit

from .helpers import SyntheticStage, context


@dataclass
class TimedStage(SyntheticStage):
    """Units sleep, fail or interrupt the process at chosen moments."""

    delays: dict[str, float] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)
    interrupting: set[str] = field(default_factory=set)

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        key = unit.recipe.unit_id
        if key in self.interrupting:
            time.sleep(0.2)
            signal.raise_signal(signal.SIGINT)
        time.sleep(self.delays.get(key, 0))
        if key in self.failing:
            raise ValueError(f"synthetic failure in {key}")
        return super().run(ctx, unit)


def writable(root: Path) -> Ledger:
    return Ledger(
        root,
        root / "work/ledger.sqlite3",
        readonly=False,
        timeout=load().resources.ledger_timeout_seconds,
    )


def recorded(ledger: Ledger) -> set[str]:
    return {record.unit_id for record in ledger.records()}


def summary(root: Path) -> dict[str, object]:
    [path] = (root / "work/runs").glob("*/summary.json")
    return dict(json.loads(path.read_bytes()))


def test_interrupt_stops_scheduling_and_records_running_units(tmp_path: Path) -> None:
    stage = TimedStage(
        "first",
        [Recipe("first", key) for key in ("fast", "slow", "later")],
        # Both workers are busy when the interrupt arrives; "later" never starts.
        delays={"fast": 1.0, "slow": 0.5},
        interrupting={"slow"},
    )
    with writable(tmp_path) as ledger:
        ctx = context(tmp_path, ledger)
        with pytest.raises(KeyboardInterrupt):
            run(ctx, [stage])
        assert recorded(ledger) == {"fast", "slow"}
        assert summary(tmp_path) == {"complete": False, "completed": 2, "skipped": 0}
        assert run(ctx, [stage]) == {"completed": 1, "skipped": 2}


def test_a_failure_lets_running_units_finish_and_record(tmp_path: Path) -> None:
    stage = TimedStage(
        "first",
        [Recipe("first", key) for key in ("broken", "slow", "later")],
        delays={"broken": 0.1, "slow": 0.4},
        failing={"broken"},
    )
    with writable(tmp_path) as ledger:
        ctx = context(tmp_path, ledger)
        with pytest.raises(ValueError, match="synthetic failure"):
            run(ctx, [stage])
        assert recorded(ledger) == {"slow"}


def test_a_failed_unit_makes_the_command_exit_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A wrapper sees the failure only in the status of the pipeline process.

    Capture it directly: `cmd; echo $?` after a pipe reports the pipe's last
    command, and an unescaped `$?` in a tmux command is expanded at launch.
    """
    root = tmp_path / "workspace"
    with writable(root):
        pass
    stage = SyntheticStage("download", [Recipe("download", "airports")], fail=True)
    monkeypatch.setattr(arguments, "registry", lambda config: [stage])
    assert main(["run", "--root", str(root)]) == 2
    assert "pipeline: synthetic interruption" in capsys.readouterr().out
    summary = next((root / "work/runs").glob("*/summary.json"))
    assert json.loads(summary.read_text())["complete"] is False
    # The module entry point turns that result into the process exit status.
    command = [sys.executable, "-m", "pipeline", "run", "--root", str(root)]
    status = subprocess.run(
        [*command, "--through", "missing"], capture_output=True, check=False
    )
    assert status.returncode == 2


def test_invalidate_requires_confirmation(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    stage = SyntheticStage("download", [Recipe("download", "airports")])
    with writable(root) as ledger:
        run(context(root, ledger), [stage])
    assert main(["invalidate", "download", "--root", str(root)]) == 2
    with Ledger(root, root / "work/ledger.sqlite3") as ledger:
        assert recorded(ledger) == {"airports"}
    assert main(["invalidate", "download", "--yes", "--root", str(root)]) == 0
    with Ledger(root, root / "work/ledger.sqlite3") as ledger:
        assert recorded(ledger) == set()


CRASH = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute("PRAGMA cache_size=1")
db.execute("BEGIN")
for i in range(2000):
    db.execute("INSERT INTO recipes VALUES ('x', ?, ?)", (str(i), "r" * 4000))
os._exit(1)
"""


def test_hot_journal_is_refused_then_recovered_by_a_writer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "workspace"
    path = root / "work/ledger.sqlite3"
    with writable(root):
        pass
    subprocess.run([sys.executable, "-c", CRASH, str(path)], check=False)
    journal = Path(str(path) + "-journal")
    assert journal.stat().st_size > 0
    with pytest.raises(ValueError, match="hot rollback journal"):
        Ledger(root, path)
    assert main(["status", "--root", str(root)]) == 2
    assert "hot rollback journal" in capsys.readouterr().out
    assert main(["gc", "--dry-run", "--root", str(root)]) == 0
    assert not journal.exists() or not journal.stat().st_size
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM recipes").fetchone() == (0,)

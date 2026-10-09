"""Units in worker processes: one ledger, global admission, clean shutdown."""

import json
import multiprocessing
import os
import shutil
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import psutil
import pytest

from pipeline.config.schema import DISK_FLOOR
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import atomic_output
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Dependency, Recipe
from pipeline.runtime.resources import ResourceGuard, tree_memory
from pipeline.runtime.runner import run
from pipeline.runtime.watch import InputsChanged
from pipeline.runtime.workers import WorkerDied
from pipeline.stages.contract import Context, Unit

from .helpers import SyntheticStage, context
from .test_code_watch import EDITED, CodeStage, edit

Action = Callable[[Context, Unit], None]


@dataclass
class ProbeStage(SyntheticStage):
    """Each unit runs its action, then records its process and timing."""

    actions: dict[str, Action] = field(default_factory=dict)
    reserve: int = 0

    def units(self, ctx: Context) -> list[Unit]:
        return [replace(u, required_bytes=self.reserve) for u in super().units(ctx)]

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        start = time.monotonic()
        if action := self.actions.get(unit.recipe.unit_id):
            action(ctx, unit)
        upstream = [
            ctx.ledger.get(*dependency.key) is not None
            for dependency in unit.recipe.dependencies
        ]
        path = ctx.root / self.name / unit.recipe.unit_id
        record = {
            "pid": os.getpid(),
            "start": start,
            "end": time.monotonic(),
            "upstream": upstream,
        }
        with atomic_output(path) as temporary:
            temporary.write_text(json.dumps(record))
        return [path]


def probe(root: Path, stage: str, unit: str) -> dict[str, object]:
    value: dict[str, object] = json.loads((root / stage / unit).read_text())
    return value


def processes(root: Path, ledger: Ledger, workers: int = 2) -> Context:
    ctx = context(root, ledger)
    ctx.config.resources.workers = workers
    ctx.config.resources.executor = "process"
    return ctx


def sleep(seconds: float) -> Action:
    return lambda ctx, unit: time.sleep(seconds)


def recorded(ledger: Ledger) -> set[str]:
    return {record.unit_id for record in ledger.records()}


def run_log(root: Path) -> str:
    return "".join(path.read_text() for path in (root / "work/runs").glob("*/run.log"))


def test_units_run_in_children_read_records_and_log_to_the_run_log(
    tmp_path: Path,
) -> None:
    first = ProbeStage(
        "first",
        [Recipe("first", key) for key in ("a", "b", "c")],
        actions={"a": lambda ctx, unit: ctx.log("hello from the child")},
    )
    second = ProbeStage(
        "second",
        [Recipe("second", "x", dependencies=(Dependency("first", "a"),))],
        needs=("first",),
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = processes(tmp_path, ledger)
        assert run(ctx, [first, second]) == {"completed": 4, "skipped": 0}
        assert run(ctx, [first, second]) == {"completed": 0, "skipped": 4}
    pids = {probe(tmp_path, "first", key)["pid"] for key in "abc"}
    assert os.getpid() not in pids and len(pids) <= 2
    assert probe(tmp_path, "second", "x")["upstream"] == [True]
    assert "hello from the child" in run_log(tmp_path)
    assert not psutil.Process().children()


def explode(ctx: Context, unit: Unit) -> None:
    raise ValueError(f"synthetic failure in {unit.recipe.unit_id}")


def test_a_child_failure_keeps_its_traceback_and_running_units(
    tmp_path: Path,
) -> None:
    stage = ProbeStage(
        "first",
        [Recipe("first", key) for key in ("broken", "slow", "later")],
        actions={"broken": explode, "slow": sleep(0.5)},
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        with pytest.raises(ValueError, match="synthetic failure") as raised:
            run(processes(tmp_path, ledger), [stage])
        assert recorded(ledger) == {"slow"}
    notes = "".join(raised.value.__notes__)
    assert "Traceback (most recent call last)" in notes and "in explode" in notes
    assert "in explode" in run_log(tmp_path)
    assert not psutil.Process().children()


def test_a_killed_worker_is_reported_and_never_recorded(tmp_path: Path) -> None:
    stage = ProbeStage(
        "first",
        [Recipe("first", key) for key in ("killed", "slow", "later")],
        actions={
            "killed": lambda ctx, unit: os.kill(os.getpid(), signal.SIGKILL),
            "slow": sleep(0.5),
        },
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        with pytest.raises(WorkerDied, match=r"first/killed ended with signal SIGKILL"):
            run(processes(tmp_path, ledger), [stage])
        assert recorded(ledger) == {"slow"}
    assert not psutil.Process().children()


def interrupt(ctx: Context, unit: Unit) -> None:
    os.kill(os.getppid(), signal.SIGINT)
    time.sleep(0.5)


def test_ctrl_c_waits_for_children_and_records_them(tmp_path: Path) -> None:
    stage = ProbeStage(
        "first",
        [Recipe("first", key) for key in ("fast", "slow", "later")],
        actions={"fast": sleep(1.0), "slow": interrupt},
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        with pytest.raises(KeyboardInterrupt):
            run(processes(tmp_path, ledger), [stage])
        assert recorded(ledger) == {"fast", "slow"}
    assert not psutil.Process().children()
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_children_never_share_admitted_bytes(tmp_path: Path) -> None:
    stage = ProbeStage(
        "first", [Recipe("first", key) for key in ("a", "b")], reserve=100
    )
    stage.actions = {"a": sleep(0.5), "b": sleep(0.5)}
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = processes(tmp_path, ledger)
        ctx.guard = ResourceGuard(
            tmp_path,
            ctx.config.resources,
            free=lambda _: DISK_FLOOR + 150,
            used=lambda _: 0,
            rss=lambda: 0,
        )
        assert run(ctx, [stage]) == {"completed": 2, "skipped": 0}
    first, second = sorted(
        (probe(tmp_path, "first", key) for key in "ab"),
        key=lambda value: float(str(value["start"])),
    )
    assert float(str(first["end"])) <= float(str(second["start"]))
    assert "paused on resources.disk_floor" in run_log(tmp_path)


def hold(ready: object, stop: object) -> None:
    payload = bytearray(b"x") * 200_000_000
    ready.set()  # type: ignore[attr-defined]
    stop.wait(30)  # type: ignore[attr-defined]
    del payload


@pytest.mark.filterwarnings("ignore:.*is multi-threaded:DeprecationWarning")
def test_tree_memory_counts_a_worker_once(tmp_path: Path) -> None:
    fork = multiprocessing.get_context("fork")
    ready, stop = fork.Event(), fork.Event()
    before = tree_memory()
    worker = fork.Process(target=hold, args=(ready, stop))
    worker.start()
    try:
        assert ready.wait(30)
        grown = tree_memory() - before
    finally:
        stop.set()
        worker.join()
    assert 150_000_000 <= grown <= 400_000_000


def test_an_edit_during_a_child_unit_stops_without_recording(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    shutil.copytree(
        REPOSITORY / "pipeline",
        repository / "pipeline",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(REPOSITORY / "uv.lock", repository / "uv.lock")
    stage = CodeStage(
        "first",
        [Recipe("first", key) for key in ("one", "two", "three")],
        repository=repository,
        actions={"one": edit(repository / EDITED)},
    )
    with Ledger(tmp_path / "workspace", None, readonly=False) as ledger:
        ctx = processes(tmp_path / "workspace", ledger)
        with pytest.raises(InputsChanged, match=EDITED):
            run(ctx, [stage])
        assert list(ledger.records()) == []
    assert not psutil.Process().children()

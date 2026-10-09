"""A run stops at the next unit boundary when hashed code changes under it."""

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pipeline.config.schema import StageSettings
from pipeline.runtime.execution import Executor
from pipeline.runtime.fingerprints import REPOSITORY, stage_identity
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Dependency, Recipe
from pipeline.runtime.runner import run
from pipeline.runtime.watch import WATCH, InputsChanged
from pipeline.stages.contract import Context, Stage, Unit

from .helpers import HashedStage, context

EDITED = "pipeline/stages/lookups.py"


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    shutil.copytree(
        REPOSITORY / "pipeline",
        root / "pipeline",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(REPOSITORY / "uv.lock", root / "uv.lock")
    return root


@dataclass
class CodeStage(HashedStage):
    """Identity is the real closure of one module in a scratch repository."""

    repository: Path = Path()
    package: str = EDITED
    actions: dict[str, Callable[[], None]] = field(default_factory=dict)

    def identity(self, ctx: Context) -> str:
        settings = StageSettings(name=self.name, packages=[self.package])
        return stage_identity(settings, ctx.config, repository=self.repository)

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        if action := self.actions.get(unit.recipe.unit_id):
            action()
        return super().run(ctx, unit)


def edit(path: Path) -> Callable[[], None]:
    def change() -> None:
        with path.open("a") as stream:
            stream.write("# edited while running\n")

    return change


def workspace(root: Path) -> Ledger:
    return Ledger(root / "workspace", None, readonly=False)


def test_edit_during_a_unit_stops_without_recording(
    tmp_path: Path, repository: Path
) -> None:
    stage = CodeStage(
        "first",
        [Recipe("first", key) for key in ("one", "two", "three")],
        repository=repository,
        actions={"one": edit(repository / EDITED)},
    )
    with workspace(tmp_path) as ledger:
        ctx = context(tmp_path / "workspace", ledger)
        ctx.config.resources.workers = 1
        with pytest.raises(InputsChanged, match=EDITED):
            run(ctx, [stage])
        assert list(ledger.records()) == []
        assert stage.calls == ["one"]


def test_edit_between_stages_stops_before_the_next_stage(
    tmp_path: Path, repository: Path
) -> None:
    first = CodeStage(
        "first", [Recipe("first", "one")], repository=repository, package=EDITED
    )
    second = CodeStage(
        "second",
        [Recipe("second", "one", dependencies=(Dependency("first", "one"),))],
        needs=("first",),
        repository=repository,
        package="pipeline/stages/cells.py",
    )
    change = edit(repository / EDITED)

    def event(message: str) -> None:
        if message == "complete first/one":
            change()

    stages: list[Stage] = [first, second]
    with workspace(tmp_path) as ledger:
        ctx = context(tmp_path / "workspace", ledger)
        with WATCH.frozen():
            executor = Executor(ctx, stages, event)
            with pytest.raises(InputsChanged, match="not recorded"):
                executor.execute("second")
        assert ledger.get("first", "one") is not None
        assert ledger.get("second", "one") is None


def test_touch_without_a_change_continues(tmp_path: Path, repository: Path) -> None:
    target = repository / EDITED

    def touch() -> None:
        os.utime(target, ns=(target.stat().st_atime_ns, target.stat().st_mtime_ns + 5))

    stage = CodeStage(
        "first",
        [Recipe("first", key) for key in ("one", "two")],
        repository=repository,
        actions={"one": touch},
    )
    with workspace(tmp_path) as ledger:
        ctx = context(tmp_path / "workspace", ledger)
        ctx.config.resources.workers = 1
        assert run(ctx, [stage]) == {"completed": 2, "skipped": 0}


def test_edits_between_runs_re_identify_the_next_run(
    tmp_path: Path, repository: Path
) -> None:
    stage = CodeStage("first", [Recipe("first", "one")], repository=repository)
    with workspace(tmp_path) as ledger:
        ctx = context(tmp_path / "workspace", ledger)
        assert run(ctx, [stage])["completed"] == 1
        edit(repository / EDITED)()
        assert run(ctx, [stage])["completed"] == 1


def test_frozen_reads_refuse_changed_bytes(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text("value = 1\n")
    with WATCH.frozen():
        assert WATCH.read(path) == b"value = 1\n"
        path.write_text("value = 22\n")
        assert WATCH.changed() == [str(path)]
        with pytest.raises(InputsChanged):
            WATCH.read(path)
    assert WATCH.read(path) == b"value = 22\n"

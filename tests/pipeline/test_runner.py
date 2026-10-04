"""Run decisions, exact dependency propagation, restoration, and crash resume."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.config import load
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import plan
from pipeline.runtime.records import Dependency, Recipe
from pipeline.runtime.runner import run
from pipeline.stages.contract import Context

from .helpers import SyntheticStage, context


def test_dynamic_units_are_discovered_after_upstream_finish(tmp_path: Path) -> None:
    first = SyntheticStage("first", [Recipe("first", "one")])
    second = SyntheticStage(
        "second",
        [Recipe("second", "two", dependencies=(Dependency("first", "one"),))],
        needs=("first",),
        discover_after="first.json",
    )
    with Ledger(
        tmp_path,
        tmp_path / "work/ledger.sqlite3",
        readonly=False,
        timeout=load().resources.ledger_timeout_seconds,
    ) as ledger:
        ctx = context(tmp_path, ledger)
        assert run(ctx, [first, second])["completed"] == 2
        assert second.calls == ["two"]
        assert run(ctx, [first, second])["completed"] == 0
        assert all(d.state == "current" for d in plan(ctx, [first, second]))


def test_upstream_change_only_rebuilds_consumers_of_changed_bytes(
    tmp_path: Path,
) -> None:
    first = SyntheticStage("first", [Recipe("first", "one"), Recipe("first", "two")])
    second = SyntheticStage(
        "second",
        [Recipe("second", "one", dependencies=(Dependency("first", "one"),))],
        needs=("first",),
    )
    with Ledger(
        tmp_path,
        tmp_path / "work/ledger.sqlite3",
        readonly=False,
        timeout=load().resources.ledger_timeout_seconds,
    ) as ledger:
        ctx = context(tmp_path, ledger)
        run(ctx, [first, second])
        first.implementation = "changed code, same bytes"
        decisions = plan(ctx, [first, second])
        assert decisions[0].reason == "identity changed"
        assert decisions[-1].reason.startswith("upstream unit changed")
        result = run(ctx, [first, second])
        assert result["completed"] == 2
        assert second.calls == ["one"]
        first.content = "changed bytes"
        ledger.invalidate("first", ["two"])
        run(ctx, [first, second])
        assert second.calls == ["one"]
        ledger.invalidate("first", ["one"])
        run(ctx, [first, second])
        assert second.calls == ["one", "one"]


def test_absent_upstream_is_materialized_only_when_needed(tmp_path: Path) -> None:
    first = SyntheticStage("first", [Recipe("first", "one")])
    second = SyntheticStage(
        "second",
        [Recipe("second", "two", dependencies=(Dependency("first", "one"),))],
        needs=("first",),
    )
    with Ledger(
        tmp_path,
        tmp_path / "work/ledger.sqlite3",
        readonly=False,
        timeout=load().resources.ledger_timeout_seconds,
    ) as ledger:
        ctx = context(tmp_path, ledger)
        run(ctx, [first, second])
        record = ledger.get("first", "one")
        assert record
        (tmp_path / "first/one").unlink()
        with ledger.transaction():
            ledger.store(
                replace(
                    record,
                    metadata={
                        **record.metadata,
                        "outputs_absent": True,
                        "absent_paths": ["first/one"],
                    },
                )
            )
        assert all(d.state == "current" for d in plan(ctx, [first, second]))
        assert run(ctx, [first, second])["completed"] == 0
        ledger.invalidate("second")
        assert run(ctx, [first, second], only="second")["completed"] == 2
        assert (tmp_path / "first/one").exists()


def test_failed_output_is_not_committed_and_resume_completes(tmp_path: Path) -> None:
    stage = SyntheticStage("first", [Recipe("first", "one")], fail=True)
    with Ledger(
        tmp_path,
        tmp_path / "work/ledger.sqlite3",
        readonly=False,
        timeout=load().resources.ledger_timeout_seconds,
    ) as ledger:
        ctx = context(tmp_path, ledger)
        with pytest.raises(ValueError, match="interruption"):
            run(ctx, [stage])
        assert ledger.get("first", "one") is None
        summaries = list((tmp_path / "work/runs").glob("*/summary.json"))
        assert json.loads(summaries[0].read_text())["complete"] is False
        assert not list(tmp_path.rglob("*.part"))
        stage.fail = False
        assert run(ctx, [stage])["completed"] == 1


def test_invalid_graph_and_target_fail_before_creating_logs(tmp_path: Path) -> None:
    stage = SyntheticStage("one", [], needs=("missing",))
    with Ledger(
        tmp_path, None, readonly=False, timeout=load().resources.ledger_timeout_seconds
    ) as ledger:
        ctx = context(tmp_path, ledger)
        with pytest.raises(ValueError, match="Unknown stage"):
            run(ctx, [stage])
        assert not (tmp_path / "work").exists()


def test_failed_finish_is_retried_without_rebuilding_units(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = SyntheticStage("first", [Recipe("first", "one")])
    with Ledger(
        tmp_path,
        tmp_path / "work/ledger.sqlite3",
        readonly=False,
        timeout=load().resources.ledger_timeout_seconds,
    ) as ledger:
        ctx = context(tmp_path, ledger)

        def interrupted_finish(ctx: Context) -> None:
            raise OSError("interrupted manifest publication")

        with monkeypatch.context() as patch:
            patch.setattr(stage, "finish", interrupted_finish)
            with pytest.raises(OSError, match="manifest"):
                run(ctx, [stage])
        assert ledger.get("first", "one") is not None
        assert not (tmp_path / "first.json").exists()
        assert run(ctx, [stage])["completed"] == 0
        assert (tmp_path / "first.json").is_file()
        assert stage.calls == ["one"]
        modified = (tmp_path / "first.json").stat().st_mtime_ns
        assert run(ctx, [stage])["completed"] == 0
        assert (tmp_path / "first.json").stat().st_mtime_ns == modified


def test_dependencies_within_a_stage_rebuild_in_one_run(tmp_path: Path) -> None:
    stage = SyntheticStage(
        "chain",
        [
            Recipe("chain", "input"),
            Recipe("chain", "result", dependencies=(Dependency("chain", "input"),)),
        ],
    )
    with Ledger(
        tmp_path,
        tmp_path / "work/ledger.sqlite3",
        readonly=False,
        timeout=load().resources.ledger_timeout_seconds,
    ) as ledger:
        ctx = context(tmp_path, ledger)
        assert run(ctx, [stage])["completed"] == 2
        stage.content = "changed bytes"
        ledger.invalidate("chain", ["input"])
        assert run(ctx, [stage])["completed"] == 2
        assert all(d.state == "current" for d in plan(ctx, [stage]))


def test_only_refreshes_ancestors_and_defers_absent_inputs_until_needed(
    tmp_path: Path,
) -> None:
    source = SyntheticStage("source", [Recipe("source", "one")])
    absent = SyntheticStage("absent", [Recipe("absent", "one")])
    chain = SyntheticStage(
        "chain",
        [
            Recipe("chain", "one", dependencies=(Dependency("source", "one"),)),
            Recipe(
                "chain",
                "two",
                dependencies=(Dependency("chain", "one"), Dependency("absent", "one")),
            ),
        ],
        needs=("source", "absent"),
    )
    stages = [source, absent, chain]
    with Ledger(
        tmp_path,
        tmp_path / "work/ledger.sqlite3",
        readonly=False,
        timeout=load().resources.ledger_timeout_seconds,
    ) as ledger:
        ctx = context(tmp_path, ledger)
        run(ctx, stages)
        record = ledger.get("absent", "one")
        assert record is not None
        (tmp_path / "absent/one").unlink()
        with ledger.transaction():
            ledger.store(
                replace(
                    record, metadata={**record.metadata, "absent_paths": ["absent/one"]}
                )
            )
        source.implementation = "changed code, same bytes"
        assert run(ctx, stages, only="chain")["completed"] == 1
        assert not (tmp_path / "absent/one").exists()
        source.implementation = "changed code and bytes"
        source.content = "changed source"
        chain.content = "changed result"
        result = run(ctx, stages, only="chain")
        assert result == {"completed": 4, "skipped": 0}
        assert (tmp_path / "absent/one").is_file()
        assert all(d.state == "current" for d in plan(ctx, stages))


def test_stage_identity_is_computed_once_per_pass_not_per_unit(
    tmp_path: Path,
) -> None:
    class CountingStage(SyntheticStage):
        identity_calls = 0

        def identity(self, ctx: Context) -> str:
            type(self).identity_calls += 1
            return super().identity(ctx)

    many = [Recipe("first", f"unit-{i}") for i in range(200)]
    first = CountingStage("first", many)
    second = CountingStage(
        "second",
        [
            Recipe(
                "second", f"unit-{i}", dependencies=(Dependency("first", f"unit-{i}"),)
            )
            for i in range(200)
        ],
        needs=("first",),
    )
    with Ledger(
        tmp_path,
        tmp_path / "work/ledger.sqlite3",
        readonly=False,
        timeout=load().resources.ledger_timeout_seconds,
    ) as ledger:
        ctx = context(tmp_path, ledger)
        run(ctx, [first, second])
        CountingStage.identity_calls = 0
        # A fully current workspace: two stage passes walk 600 unit refreshes,
        # which must not each hash the stage's code closure again.
        assert run(ctx, [first, second])["completed"] == 0
        assert CountingStage.identity_calls <= 8

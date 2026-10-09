"""Consumers name the upstream outputs they read; only those are restored."""

from dataclasses import replace
from pathlib import Path

from pipeline.runtime.ledger import Ledger
from pipeline.runtime.outputs import selected
from pipeline.runtime.records import Dependency, Recipe
from pipeline.runtime.runner import run

from .geographic_fixtures import build, geographic_graph, source_receipts
from .helpers import HashedStage, SyntheticStage, context


def offload(ledger: Ledger, root: Path, stage: str, unit: str, suffix: str) -> None:
    record = ledger.get(stage, unit)
    assert record is not None
    [path] = [o.path for o in record.outputs if o.path.endswith(suffix)]
    (root / path).unlink()
    with ledger.transaction():
        ledger.store(
            replace(record, metadata={**record.metadata, "absent_paths": [path]})
        )


def test_absent_outputs_a_consumer_does_not_read_are_not_restored(
    tmp_path: Path,
) -> None:
    first = HashedStage("first", [Recipe("first", "one")])
    second = SyntheticStage(
        "second",
        [
            Recipe(
                "second",
                "one",
                dependencies=(Dependency("first", "one", paths=("first/one",)),),
            )
        ],
        needs=("first",),
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = context(tmp_path, ledger)
        run(ctx, [first, second])
        offload(ledger, tmp_path, "first", "one", ".json")
        second.implementation = "consumer change"
        assert run(ctx, [first, second]) == {"completed": 1, "skipped": 1}
        assert first.calls == ["one"]
        offload(ledger, tmp_path, "first", "one", "/one")
        second.implementation = "another consumer change"
        assert run(ctx, [first, second])["completed"] == 2
        assert first.calls == ["one", "one"]


def test_production_read_patterns_select_recorded_outputs(tmp_path: Path) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx, normalized = source_receipts(tmp_path, ledger)
        build(ctx, geographic_graph(ctx, normalized))
        narrowed = 0
        for recipe in ledger.recipes():
            for dependency in recipe.dependencies:
                if not dependency.paths:
                    continue
                record = ledger.get(*dependency.key)
                assert record is not None
                for pattern in dependency.paths:
                    assert selected(record.outputs, (pattern,), record.inputs_hash), (
                        recipe.key,
                        pattern,
                    )
                narrowed += 1
        assert narrowed >= 4

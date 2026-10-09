"""Concurrent units record exactly what one worker records."""

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from pipeline.engines.cache import Cache
from pipeline.runtime.jsonio import Object
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.outputs import role
from pipeline.runtime.records import Recipe
from pipeline.runtime.runner import run
from pipeline.stages.contract import Context, Unit

from .geographic_fixtures import build, geographic_graph, source_receipts
from .helpers import SyntheticStage, context


def outputs(root: Path, workers: int, threads: int) -> set[tuple[str, str, str, str]]:
    with Ledger(root, None, readonly=False) as ledger:
        ctx, normalized = source_receipts(root, ledger, wide=True)
        ctx.config.resources.workers = workers
        ctx.config.resources.duckdb_threads = threads
        build(ctx, geographic_graph(ctx, normalized))
        return {
            (
                record.stage,
                record.unit_id,
                role(output.path, (record.inputs_hash,)),
                output.sha256,
            )
            for record in ledger.records()
            for output in record.outputs
        }


def test_four_workers_record_the_same_outputs_as_one(tmp_path: Path) -> None:
    serial = outputs(tmp_path / "serial", 1, 1)
    assert {key[:2] for key in serial} >= {
        ("normalize_cells", "places/YY"),
        ("normalize_cells", "quality/ZZ"),
        ("lookups", "manifest/current"),
    }
    assert len({key[1] for key in serial if key[0] == "cells"}) >= 7
    assert outputs(tmp_path / "parallel", 4, 2) == serial


def test_prepared_values_are_never_shared_between_threads() -> None:
    cache: Cache[str, object] = Cache(per_thread=True)
    made: list[object] = []

    def get() -> None:
        made.append(cache.get("polygon", object, 4))

    threads = [threading.Thread(target=get) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    get()
    get()
    assert len({id(value) for value in made}) == 5


@dataclass
class MutatingStage(SyntheticStage):
    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        time.sleep(0.2)  # both units are submitted before either edits
        cast(Object, unit.recipe.parameters["policy"])["edited"] = True
        return super().run(ctx, unit)


def test_a_unit_that_edits_shared_parameters_is_refused(tmp_path: Path) -> None:
    policy: Object = {"threshold": 1}
    stage = MutatingStage(
        "first", [Recipe("first", key, {"policy": policy}) for key in ("a", "b")]
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        with pytest.raises(ValueError, match="changed its recipe parameters"):
            run(context(tmp_path, ledger), [stage])
        assert list(ledger.records()) == []

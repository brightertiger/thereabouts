"""Actual country and block engines run through the single ledger on tiny inputs."""

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from pipeline.engines.serving.snapshot import read_snapshot
from pipeline.runtime.execution import Executor
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import plan
from pipeline.runtime.records import Recipe
from pipeline.stages import engine_io
from pipeline.stages.contract import Stage, make_unit
from pipeline.stages.registry import ordered, registry

from .geographic_fixtures import source_receipts
from .helpers import SyntheticStage


def test_country_block_and_city_stages_resume_and_repair_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx, normalized = source_receipts(tmp_path, ledger)
        stages: list[Stage] = [
            normalized,
            *[
                stage
                for stage in registry(ctx.config)
                if stage.name in {"reconcile", "cells", "cities"}
            ],
        ]
        stages = ordered(stages)
        executor = Executor(ctx, stages, lambda _: None)
        executor.execute("cells")
        executor.execute("cities")
        block = ctx.config.engines.blocks[0]
        output = engine_io.artifact(ctx, "cells", "block/" + block, suffix=".parquet")
        original = output.read_bytes()
        before = output.stat().st_mtime_ns
        executor.execute("cells")
        assert output.stat().st_mtime_ns == before
        output.write_bytes(b"corrupt")
        ctx.verifier.cache.clear()
        executor.execute("cells")
        assert output.read_bytes() == original
        assert ledger.get("cells", "snapshot/current") is not None
        assert ledger.get("cities", "mapping/ZZ") is not None
        assert pq.read_metadata(output).num_rows > 0
        # The review gate itself is tested separately; this fixture supplies one
        # accepted receipt so the actual block/table normalization can be tested.
        review = SyntheticStage("evaluate", [Recipe("evaluate", "pilot")])
        unit = make_unit(ctx, review.recipes[0], review.identity(ctx))
        gate = tmp_path / "evaluation.json"
        write_json(gate, {"passed": True})
        ledger.register(unit.recipe)
        ledger.complete(
            *unit.key,
            unit.inputs_hash,
            [gate],
            metadata={
                "identity": unit.identity,
                "dependency_hash": unit.dependency_hash,
            },
        )
        normalization = next(
            stage for stage in registry(ctx.config) if stage.name == "normalize_cells"
        )
        stages = ordered([*stages, review, normalization])
        executor = Executor(ctx, stages, lambda _: None)
        executor.execute("normalize_cells")
        completed = ledger.get("normalize_cells", "block/" + block)
        assert completed is not None
        assert len(engine_io.outputs(ctx, "normalize_cells", "places/ZZ")) == 3
        assert all(
            decision.state == "current"
            for decision in plan(ctx, stages)
            if decision.stage == "normalize_cells"
        )
        final_stages = [
            stage
            for stage in registry(ctx.config)
            if stage.name in {"lookups", "plate_country"}
        ]
        stages = ordered([*stages, *final_stages])
        Executor(ctx, stages, lambda _: None).execute("lookups")
        manifest = engine_io.artifact(
            ctx, "lookups", "manifest/current", suffix="manifest.json"
        )
        snapshot = read_snapshot(manifest, root=tmp_path)
        assert snapshot.tables("cells") and snapshot.tables("place_to_city")
        with pytest.raises(ValueError, match="pilot quality gate failed"):
            Executor(ctx, stages, lambda _: None).execute("reconcile")
        assert ledger.get("reconcile", "gate/pilot") is None
        assert ledger.get("reconcile", "manifest/current") is None
        for record in ledger.records():
            assert all(not Path(output.path).is_absolute() for output in record.outputs)

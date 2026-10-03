"""Evaluation gates order work without invalidating unrelated country payloads."""

from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from pipeline.runtime.jsonio import Object
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Dependency, Recipe, recipe_from_json
from pipeline.runtime.runner import run

from .helpers import SyntheticStage, context


def test_changed_gate_runs_before_skipping_unchanged_consumer(tmp_path: Path) -> None:
    gate = SyntheticStage("gate", [Recipe("gate", "pilot")])
    recipe = Recipe(
        "country", "BE", dependencies=(Dependency("gate", "pilot", control=True),)
    )
    country = SyntheticStage("country", [recipe], needs=("gate",))
    assert recipe_from_json(cast(Object, asdict(recipe))) == recipe
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = context(tmp_path, ledger)
        assert run(ctx, [gate, country])["completed"] == 2
        gate.implementation = "new policy review"
        gate.content = "different review receipt"
        assert run(ctx, [gate, country], only="country")["completed"] == 1
        assert country.calls == ["BE"]
        gate.implementation = "failing review"
        gate.fail = True
        ledger.invalidate("country")
        with pytest.raises(ValueError, match="synthetic interruption"):
            run(ctx, [gate, country], only="country")
        assert country.calls == ["BE"]


def test_control_dependency_cannot_claim_consumed_paths() -> None:
    with pytest.raises(ValueError, match="control dependency"):
        Dependency("gate", "pilot", ("receipt.json",), control=True)

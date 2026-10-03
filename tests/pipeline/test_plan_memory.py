"""Checking registration does not decode every saved policy in the ledger."""

from pathlib import Path

import pytest

from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import plan
from pipeline.runtime.records import Recipe

from .helpers import SyntheticStage, context


def test_plan_reads_stage_names_without_materializing_saved_recipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        stage = SyntheticStage("sample", [Recipe("sample", "one")])
        ledger.register(stage.recipes[0])

        def unexpected(*args: object) -> None:
            raise AssertionError("Plan must not load all stored policy objects")

        monkeypatch.setattr(ledger, "recipes", unexpected)
        assert plan(context(tmp_path, ledger), [stage])[0].state == "new"
        ledger.register(Recipe("unknown", "one"))
        with pytest.raises(ValueError, match="unregistered stages"):
            plan(context(tmp_path, ledger), [stage])

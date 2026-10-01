from __future__ import annotations

from pathlib import Path

import pytest
from h3.api import basic_int as h3

from build_data.golden import blocks
from build_data.golden.planning import Dependencies


def test_changed_country_dependencies_reuse_finest_envelopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = h3.latlng_to_cell(0, 0, 3)
    monkeypatch.setattr(blocks, "blocks", lambda: [root])
    path = tmp_path / "blocks.sqlite"
    plan = blocks.Plan(path, Dependencies({"bounds": [["AA", -5, -5, 5, 5]]}, 1000))
    try:
        plan.create()
        assert plan.rows()[0]["countries"] == ["AA"]
    finally:
        plan.close()

    def no_enumeration(*args: object) -> None:
        raise AssertionError("unchanged H3 envelopes must be reused")

    monkeypatch.setattr(blocks, "descendants", no_enumeration)
    plan = blocks.Plan(path, Dependencies({"bounds": [["BB", -5, -5, 5, 5]]}, 1000))
    try:
        plan.create()
        assert plan.rows()[0]["countries"] == ["BB"]
        plan.create()
        assert plan.rows()[0]["countries"] == ["BB"]
    finally:
        plan.close()

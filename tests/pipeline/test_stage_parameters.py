"""Stage-owned parameter callbacks preserve policy scope and execution decisions."""

from pathlib import Path

import pytest

from pipeline.config import load
from pipeline.runtime.jsonio import Object, digest
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe
from pipeline.stages import cells, cities, normalize_cells, parameters
from pipeline.stages.engine_data import Geography

from .helpers import context


def test_country_policy_edit_changes_only_reading_country_or_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value: Object = {
        "rule": "shared",
        "countries": {"BE": {"rule": 1}, "IN": {"rule": 2}},
    }
    monkeypatch.setattr(parameters, "cities", lambda ctx: value)
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = context(tmp_path, ledger)
        ctx.config = load()
        geo = Geography(["BE", "IN"], {"belgium": ["BE"], "mixed": ["BE", "IN"]})

        def hashes() -> list[str]:
            city = cities.parameters(ctx, geo)
            block = normalize_cells.parameters(ctx, geo)
            return [
                digest(city(Recipe("cities", "country/BE")).parameters),
                digest(city(Recipe("cities", "country/IN")).parameters),
                digest(block(Recipe("normalize_cells", "block/belgium")).parameters),
                digest(block(Recipe("normalize_cells", "block/mixed")).parameters),
            ]

        before = hashes()
        value["countries"] = {"BE": {"rule": 1}, "IN": {"rule": 3}}
        after = hashes()
        assert [a != b for a, b in zip(before, after, strict=True)] == [
            False,
            True,
            False,
            True,
        ]
        configured = cells.parameters(ctx, geo)
        assert configured(Recipe("cells", "plan/countries")).refresh_discovery
        block = configured(Recipe("cells", "block/belgium"))
        assert block.parameters["countries"] == ["BE"]
        assert block.required_bytes == ctx.config.engines.limits.block_reservation_bytes
        assert not block.refresh_discovery

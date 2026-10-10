"""Spatial findings block in reviewed countries and are advisory elsewhere."""

import pytest

from pipeline.engines.cities.gate_scope import counts, reviewed_countries, scoped
from pipeline.engines.store.codec import Row


def loss(cc: str, lost: int = 2) -> Row:
    return {"country": cc, "city_id": f"city:{cc}", "lost_cells": lost}


def footprint(cc: str) -> Row:
    return {"country": cc, "city_id": f"city:{cc}", "after": {"share": 0.5}}


FAILED: Row = {
    "footprints": [footprint("GB"), footprint("DE")],
    "neighbours": [{"city_id": "city:DE"}],
    "named": [{"country": "DE", "passed": False}],
    "all_boundaries": [loss("GB"), loss("DE", 3), loss("DE", 4)],
}


def test_reviewed_countries_join_both_pilots_policies_and_exceptions() -> None:
    reviewed = reviewed_countries(
        {"pilot": ["IN", "CN"], "countries": {"MY": {}}},
        {"pilot": ["JP", "IN"]},
        {"boundary_exceptions": [{"country": "US"}]},
    )
    assert reviewed == ["CN", "IN", "JP", "MY", "US"]


def test_reviewed_scope_blocks_reviewed_countries_and_records_the_rest() -> None:
    blocking, advisory = scoped(
        FAILED, {"blocking_scope": "reviewed", "reviewed": ["GB"]}
    )
    assert blocking == {
        "footprints": [footprint("GB")],
        "neighbours": FAILED["neighbours"],
        "named": FAILED["named"],
        "all_boundaries": [loss("GB")],
    }
    assert advisory == {
        "footprints": [footprint("DE")],
        "all_boundaries": [loss("DE", 3), loss("DE", 4)],
    }
    # Every finding is kept exactly once.
    for kind in ("footprints", "all_boundaries"):
        assert sorted(map(str, blocking[kind] + advisory[kind])) == sorted(
            map(str, FAILED[kind])
        )


def test_all_scope_blocks_every_country() -> None:
    blocking, advisory = scoped(FAILED, {"blocking_scope": "all", "reviewed": ["GB"]})
    assert blocking == FAILED
    assert advisory == {"footprints": [], "all_boundaries": []}


def test_unknown_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="blocking scope"):
        scoped(FAILED, {"blocking_scope": "pilot", "reviewed": []})


def test_counts_are_per_country() -> None:
    assert counts(FAILED) == {
        "DE": {"boundary_losses": 2, "lost_cells": 7, "footprint_failures": 1},
        "GB": {"boundary_losses": 1, "lost_cells": 2, "footprint_failures": 1},
    }

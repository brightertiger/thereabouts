"""Spatial release failures and review receipts tied to measured artifacts."""

from pathlib import Path

import pytest

from pipeline.engines.cities.gates import failures
from pipeline.engines.store.codec import Row


def test_spatial_gate_rejects_footprint_and_neighbour_losses() -> None:
    result = failures(
        [
            {
                "footprints": [{"after": {"eligible": 100, "share": 0.98}}],
                "neighbours": [
                    {
                        "city_id": "own",
                        "point_after": {"city_id": "other"},
                        "polygon_after": {"expected": 9},
                        "polygon_before": {"expected": 10},
                    }
                ],
            }
        ],
        [{"passed": False}],
    )
    assert {k: len(v) for k, v in result.items()} == {
        "footprints": 1,
        "neighbours": 1,
        "named": 1,
        "all_boundaries": 0,
    }


def test_reviewed_gate_refuses_changed_policy(tmp_path: Path) -> None:
    from pipeline.config.reviews import load
    from pipeline.runtime.jsonio import digest, write_json

    settings: Row = {"pilot": ["ZZ"], "town_radius": {"enabled": False}}
    gate = tmp_path / "review.yaml"
    write_json(
        gate,
        {
            "accepted": True,
            "review": "All measured losses reviewed",
            "policy_fingerprint": digest(settings),
        },
    )
    load(gate, settings)
    settings["town_radius"]["enabled"] = True
    with pytest.raises(ValueError, match="Policy changed"):
        load(gate, settings)


def test_boundary_exception_is_exact_and_explained() -> None:
    from pipeline.engines.cities.gates import unreviewed

    loss = {"country": "ZZ", "city_id": "town", "lost_cells": 1, "lost_to": {"part": 1}}
    assert unreviewed([loss], [loss]) == [loss]
    approved = {
        **loss,
        "reason": "Overlapping source boundaries",
        "reference": "Retained polygons",
    }
    assert unreviewed([loss], [approved]) == []
    assert unreviewed([{**loss, "lost_cells": 2}], [approved])


def test_distinct_boundaries_of_one_city_keep_separate_reviews() -> None:
    from pipeline.engines.cities.gates import unreviewed

    first = {
        "country": "ZZ",
        "city_id": "town",
        "lost_cells": 1,
        "lost_to": {"neighbour": 1},
        "references": ["municipal-relation"],
    }
    second = {
        **first,
        "lost_cells": 2,
        "lost_to": {"neighbour": 2},
        "references": ["way"],
    }
    reviews = [
        {
            **loss,
            "boundary_references": loss["references"],
            "reason": "Individually examined overlap",
            "reference": "Source polygons and cell coordinates",
        }
        for loss in [first, second]
    ]
    assert unreviewed([first, second], reviews) == []
    assert unreviewed([first, second], reviews[:1]) == [second]
    unrelated = {**first, "references": ["another-polygon"]}
    assert unreviewed([unrelated], reviews) == [unrelated]

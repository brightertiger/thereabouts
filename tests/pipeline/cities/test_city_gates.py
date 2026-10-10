"""Spatial release failures and review receipts tied to measured artifacts."""

from collections.abc import Callable
from pathlib import Path

import pytest

from pipeline.engines.cities.gates import failures, unreviewed
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


def stored(*areas: str) -> dict[str, str]:
    """One build's sequence IDs for upstream records, as a reconcile database."""
    return {str(10 * i + 7): record for i, record in enumerate(areas)}


def resolver(build: dict[str, str]) -> Callable[[Row], list[str]]:
    return lambda loss: sorted({build[r] for r in loss["references"]})


LOSS: Row = {
    "country": "ZZ",
    "city_id": "town",
    "lost_cells": 1,
    "lost_to": {"neighbour": 1},
    "loss_examples": [{"h3": "882ab2cda1fffff", "after": "neighbour"}],
}
REVIEW: Row = {
    "country": "ZZ",
    "city_id": "town",
    "lost_cells": 1,
    "lost_to": {"neighbour": 1},
    "cells": {"882ab2cda1fffff": "neighbour"},
    "boundary_origins": ["osm:r1", "osm:w2"],
    "reason": "Overlapping source boundaries",
    "reference": "Retained polygons",
}


def test_boundary_exception_survives_a_rebuild_that_renumbers_areas() -> None:
    first = stored("osm:r1", "osm:w2", "osm:r3")
    rebuilt = stored("osm:r3", "osm:x9", "osm:w2", "osm:r1")
    old = {**LOSS, "references": ["7", "17"]}
    new = {**LOSS, "references": ["37", "27"]}
    assert unreviewed([old], [REVIEW], resolver(first)) == []
    assert unreviewed([new], [REVIEW], resolver(rebuilt)) == []
    # Matching sequence IDs from another build are not evidence.
    assert unreviewed([old], [REVIEW], resolver(rebuilt)) == [old]


@pytest.mark.parametrize(
    "change",
    [
        {"lost_to": {"other": 1}},
        {
            "lost_cells": 2,
            "lost_to": {"neighbour": 2},
            "loss_examples": [
                *LOSS["loss_examples"],
                {"h3": "882ab2cda3fffff", "after": "neighbour"},
            ],
        },
        {"loss_examples": [{"h3": "882ab2cda3fffff", "after": "neighbour"}]},
        {"loss_examples": [{"h3": "882ab2cda1fffff", "after": "other"}]},
        {"loss_examples": []},
        {"references": ["7"]},
        {"references": ["7", "17", "27"]},
        {"city_id": "other"},
    ],
)
def test_boundary_exception_needs_exactly_matching_evidence(change: Row) -> None:
    build = stored("osm:r1", "osm:w2", "osm:r3")
    loss = {**LOSS, "references": ["7", "17"], **change}
    assert unreviewed([loss], [REVIEW], resolver(build)) == [loss]


def test_boundary_exception_requires_an_explanation_and_stable_origins() -> None:
    loss = {**LOSS, "references": ["7", "17"]}
    build = resolver(stored("osm:r1", "osm:w2"))
    for missing in ("reason", "reference", "boundary_origins", "cells"):
        review = {k: v for k, v in REVIEW.items() if k != missing}
        assert unreviewed([loss], [review], build) == [loss]


def test_distinct_boundaries_of_one_city_keep_separate_reviews() -> None:
    build = stored("osm:r1", "osm:w2")
    first = {**LOSS, "references": ["7"]}
    second = {
        **LOSS,
        "lost_cells": 2,
        "lost_to": {"neighbour": 2},
        "loss_examples": [
            {"h3": "882ab2cda3fffff", "after": "neighbour"},
            {"h3": "882ab2cda5fffff", "after": "neighbour"},
        ],
        "references": ["17"],
    }
    reviews = [
        {**REVIEW, "boundary_origins": ["osm:r1"]},
        {
            **REVIEW,
            "lost_cells": 2,
            "lost_to": {"neighbour": 2},
            "cells": {"882ab2cda3fffff": "neighbour", "882ab2cda5fffff": "neighbour"},
            "boundary_origins": ["osm:w2"],
        },
    ]
    assert unreviewed([first, second], reviews, resolver(build)) == []
    assert unreviewed([first, second], reviews[:1], resolver(build)) == [second]


def test_origins_resolve_only_for_otherwise_matching_losses() -> None:
    calls: list[str] = []

    def origins(loss: Row) -> list[str]:
        calls.append(loss["city_id"])
        return ["osm:r1", "osm:w2"]

    unrelated = {**LOSS, "city_id": "elsewhere", "references": ["1"]}
    changed = {**LOSS, "lost_to": {"other": 1}, "references": ["1"]}
    exact = {**LOSS, "references": ["1"]}
    assert unreviewed([unrelated, changed, exact], [REVIEW], origins) == [
        unrelated,
        changed,
    ]
    assert calls == ["town"]


def test_review_refuses_sequence_ids_and_inconsistent_cells(tmp_path: Path) -> None:
    from pipeline.config.reviews import load
    from pipeline.runtime.jsonio import digest, write_json

    settings: Row = {"pilot": ["ZZ"]}
    exception = dict(REVIEW)
    gate = tmp_path / "review.yaml"

    def review(**change: object) -> list[str]:
        write_json(
            gate,
            {
                "accepted": True,
                "review": "All measured losses reviewed",
                "policy_fingerprint": digest(settings),
                "boundary_exceptions": [{**exception, **change}],
            },
        )
        return load(gate, settings).boundary_exceptions[0].boundary_origins

    assert review() == ["osm:r1", "osm:w2"]
    with pytest.raises(ValueError, match="sequence IDs"):
        review(boundary_origins=["23017", "23071"])
    changes: list[Row] = [
        {"boundary_origins": []},
        {"boundary_origins": ["osm:r1", "osm:r1"]},
        {"cells": {}},
        {"cells": {"882ab2cda1fffff": "other"}},
        {"cells": {"882ab2cda1fffff": "neighbour", "882ab2cda3fffff": "neighbour"}},
        {"cells": {"not-a-cell": "neighbour"}},
    ]
    for bad in changes:
        with pytest.raises(ValueError, match="Incomplete boundary exception"):
            review(**bad)
    with pytest.raises(ValueError, match="Invalid review"):
        review(boundary_references=["23017"])

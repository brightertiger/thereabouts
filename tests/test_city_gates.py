"""Spatial release failures and review receipts tied to measured artifacts."""

from pathlib import Path

import pytest

from build_data.acquire.artifacts import file_record
from build_data.acquire.io import fingerprint, write_json
from build_data.golden.inputs import Inputs
from build_data.normalize_cells.gates import failures, reviewed
from build_data.reconcile.common import Row


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


def test_reviewed_gate_refuses_mutated_pilot_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("build_data.normalize_cells.gates.builder", lambda: "code")
    settings: Row = {"pilot": ["ZZ"], "town_radius": {"enabled": False}}
    inputs = Inputs({}, {}, {}, {}, "source-code")
    base: Row = {"completed": True}
    ghsl: Row = {"source": "ghsl"}
    normalized = {"builder": "code", "policy": settings}
    report_path = tmp_path / "report.json"
    write_json(report_path, {"before": 1, "after": 2})
    normal_path = tmp_path / "normalization.json"
    write_json(normal_path, normalized)
    summary_path = tmp_path / "summary.json"
    write_json(
        summary_path,
        {
            "normalization": fingerprint(normalized),
            "base": fingerprint(base),
            "variants": {
                "off": {
                    "automated_gate": True,
                    "countries": {"ZZ": str(report_path)},
                    "report_artifacts": [file_record(report_path)],
                }
            },
        },
    )
    decision = {
        "accepted": True,
        "builder": "code",
        "policy": fingerprint(settings),
        "inputs": inputs.identity,
        "base": fingerprint(base),
        "ghsl": fingerprint(ghsl),
        "review": "All observed losses reviewed",
        "unresolved_losses": [],
        "pilot_summary": file_record(summary_path),
        "normalization_manifest": file_record(normal_path),
    }
    gate = tmp_path / "gate.json"
    write_json(gate, decision)
    reviewed(gate, settings, inputs, base, ghsl)
    write_json(report_path, {"before": 1, "after": 0})
    with pytest.raises(ValueError, match="verification failed"):
        reviewed(gate, settings, inputs, base, ghsl)


def test_boundary_exception_is_exact_and_explained() -> None:
    from build_data.normalize_cells.gates import unreviewed

    loss = {"country": "ZZ", "city_id": "town", "lost_cells": 1, "lost_to": {"part": 1}}
    assert unreviewed([loss], [loss]) == [loss]
    approved = {
        **loss,
        "reason": "Overlapping source boundaries",
        "reference": "Retained polygons",
    }
    assert unreviewed([loss], [approved]) == []
    assert unreviewed([{**loss, "lost_cells": 2}], [approved])

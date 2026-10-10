"""The e2e lookups-gate check over a small synthetic workspace."""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pipeline.engines.artifact_io import file_record
from pipeline.engines.artifacts import read_json
from pipeline.runtime.jsonio import sha256_file, write_json
from tests.pipeline.release import synthetic

from . import driver

Row = dict[str, Any]


def build(root: Path, report: Row, gates: Row | None = None) -> Path:
    """A lookups manifest, its quality.json and pointer, and a release that read it.

    Returns the dataset directory; the workspace is `root`."""
    quality = root / "work/lookups/quality.json"
    write_json(quality, report)
    gates = gates or synthetic.gates(report)
    record = file_record(root, quality)
    manifest = root / "work/lookups/manifest.json"
    write_json(
        manifest,
        {"completed": True, "verification_artifacts": [record], "quality_gates": gates},
    )
    write_json(root / "cells/current.json", {"manifest": file_record(root, manifest)})
    dataset = root / "dataset/2026.10"
    write_json(
        dataset / "manifest.json",
        {
            "input_manifest_sha256": sha256_file(manifest),
            "quality_gates": {**gates, "report": record},
        },
    )
    return dataset


def reviewed() -> list[str]:
    return list(driver.configured_gates()["reviewed_countries"])


def checked(root: Path, dataset: Path) -> driver.Step:
    report = driver.Report(driver.Settings(release=root, work=root, workspace=root))
    driver.quality_gates(report, dataset)
    return report.step("quality-gates")


def test_configured_gates_follow_the_repository_policies() -> None:
    gates = driver.configured_gates()
    assert gates["blocking_scope"] == "reviewed"
    assert {"FR", "GB", "IN", "JP", "US"} <= set(gates["reviewed_countries"])
    assert gates["reviewed_countries"] == sorted(gates["reviewed_countries"])


def test_a_consistent_workspace_passes_and_reports_totals(tmp_path: Path) -> None:
    dataset = build(tmp_path, synthetic.quality(reviewed()))
    record = checked(tmp_path, dataset)
    assert record.status == "pass", record.error
    details = record.details
    assert details["blocking_scope"] == "reviewed"
    assert details["reviewed_countries"] == len(reviewed())
    assert details["advisory"] == {
        "countries": 2,
        "boundary_losses": 2,
        "lost_cells": 42,
        "footprint_failures": 1,
    }
    assert [row["country"] for row in details["top"]] == ["DE", "BR"]
    report = driver.Report(driver.Settings(release=tmp_path, work=tmp_path))
    report.steps.append(record)
    text = driver.markdown(report)
    assert "## Lookups quality gates" in text
    assert "2 boundary losses (42 cells) and 1 footprint failure" in text
    assert "| DE | 1 | 40 | 0 |" in text


def test_without_a_workspace_the_check_is_skipped(tmp_path: Path) -> None:
    report = driver.Report(driver.Settings(release=tmp_path, work=tmp_path))
    driver.quality_gates(report, tmp_path)
    assert report.step("quality-gates").status == "skip"


def reviewed_finding(report: Row) -> None:
    report["advisory_spatial_gates"]["footprints"][0]["country"] = "FR"


def blocking_finding(report: Row) -> None:
    report["failed_spatial_gates"]["named"].append({"country": "FR", "id": "x"})


def inflated(report: Row) -> None:
    report["gate_scope"]["advisory"]["lost_cells"] += 1


def fewer_reviewed(report: Row) -> None:
    report["gate_scope"]["reviewed_countries"] = report["gate_scope"][
        "reviewed_countries"
    ][1:]


def every_country(report: Row) -> None:
    report["gate_scope"]["blocking_scope"] = "all"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (reviewed_finding, "advisory findings in reviewed countries: ['FR']"),
        (blocking_finding, "blocking findings: {'named': 1}"),
        (inflated, "advisory totals disagree"),
        (fewer_reviewed, "reviewed_countries differs from the repository"),
        (every_country, "blocking_scope differs from the repository"),
    ],
)
def test_inconsistent_gates_fail(
    tmp_path: Path, change: Callable[[Row], None], message: str
) -> None:
    report = copy.deepcopy(synthetic.quality(reviewed()))
    change(report)
    record = checked(tmp_path, build(tmp_path, report))
    assert record.status == "fail"
    assert message in (record.error or "")


def test_a_release_built_from_another_manifest_fails(tmp_path: Path) -> None:
    dataset = build(tmp_path, synthetic.quality(reviewed()))
    manifest = tmp_path / "work/lookups/manifest.json"
    write_json(manifest, {**read_json(manifest), "rebuilt": True})
    write_json(
        tmp_path / "cells/current.json", {"manifest": file_record(tmp_path, manifest)}
    )
    error = checked(tmp_path, dataset).error or ""
    assert "not this release's input" in error


def test_changed_quality_bytes_fail(tmp_path: Path) -> None:
    dataset = build(tmp_path, synthetic.quality(reviewed()))
    with (tmp_path / "work/lookups/quality.json").open("a") as stream:
        stream.write(" ")
    assert "checksum differs" in (checked(tmp_path, dataset).error or "")


def test_release_gates_must_match_their_input(tmp_path: Path) -> None:
    dataset = build(tmp_path, synthetic.quality(reviewed()))
    write_json(
        dataset / "manifest.json",
        {**read_json(dataset / "manifest.json"), "quality_gates": None},
    )
    error = checked(tmp_path, dataset).error or ""
    assert "release's quality_gates differ" in error

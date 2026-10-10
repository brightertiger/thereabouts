"""The end-to-end driver passes on a fixture-scale release built by the pipeline."""

import shutil
from pathlib import Path
from typing import Any

import pytest

from pipeline.config.release import PublishSettings
from pipeline.engines.artifact_io import file_record
from pipeline.release import acceptance, bundle, client
from pipeline.release.publish import inventory, publish
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.resources import ResourceGuard
from tests.pipeline.release.synthetic import dataset as synthetic_dataset
from tests.pipeline.release.synthetic import quality
from tests.pipeline.sources import plate_evaluation

from . import driver

FAMILIES = driver.FAMILIES


def staged(root: Path) -> Path:
    """The packs stage and a private file:// publication, as on the VM."""
    reviewed = driver.configured_gates()["reviewed_countries"]
    dataset, config = synthetic_dataset(root, quality(reviewed))
    packs = root / "packs/2026.10"
    guard = ResourceGuard(root, config.resources)
    writer = client.binding()
    accept = config.release.acceptance
    accept.ocean_points = 40
    for family in FAMILIES:
        client.write(dataset, family, packs / family, "2026.10", writer)
        acceptance.accept(dataset, packs, family, "2026.10", accept)
        bundle.archive(packs / family, guard)
    bundle.index(packs, "2026.10", list(FAMILIES))
    staging = root / "staging"
    entries = inventory(dataset, {f: packs / f for f in FAMILIES}, "2026.10")
    # The synthetic plates are CC BY-SA: an owner decision, so staging is private.
    publish(
        entries,
        staging.as_uri(),
        "2026.10",
        PublishSettings(private=True),
        dry_run=False,
    )
    return staging


def workspace(root: Path, lookups: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pinned plate_country evidence holding one Commons evaluation page, and the
    lookups manifest and quality.json the release was assembled from."""
    root.mkdir(parents=True)
    shutil.copyfile(lookups / "quality.json", root / "quality.json")
    shutil.copyfile(lookups / "manifest.json", root / "lookups.json")
    write_json(
        root / "cells/current.json",
        {"manifest": file_record(root, root / "lookups.json")},
    )
    page = root / "raw/plate_country/sha256/commons"
    write_json(
        page,
        {
            "query": {
                "pages": {
                    "7": {
                        "title": "File:Car AB-123-CD 75.jpg",
                        "revisions": [{"revid": 9}],
                        "imageinfo": [
                            {
                                "url": "https://example.invalid/photo",
                                "sha1": "unused",
                                "extmetadata": {"LicenseShortName": {"value": "CC0"}},
                            }
                        ],
                    }
                }
            }
        },
    )
    sources = root / "normalized/plate_country/evidence/hash/sources.json"
    record: dict[str, Any] = {"name": "eval-commons-FR.json", **file_record(root, page)}
    write_json(sources, {"sources": [record]})
    write_json(
        root / "normalized/plate_country/manifest.json",
        {"source": "plate_country", "auxiliary": [file_record(root, sources)]},
    )
    rule = {
        "country_code": "FR",
        "source": "eval-commons-FR.json",
        "page_id": 7,
        "field": "title",
        "pattern": r"(?P<plate>AB-123-CD 75)",
        "method": "source_transcription",
    }
    monkeypatch.setattr(plate_evaluation, "policy", lambda name: [rule])
    return root


def test_the_driver_passes_on_a_fixture_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = staged(tmp_path / "build")
    lookups = tmp_path / "build/input"
    settings = driver.Settings(
        release=staging,
        work=tmp_path / "work",
        land_cells=50,
        ocean_points=30,
        names=20,
        forward_rows=10,
        cross_client=40,
        timeout=600,
        workspace=workspace(tmp_path / "workspace", lookups, monkeypatch),
    )
    report = driver.run(settings)
    text = driver.markdown(report)
    (tmp_path / "e2e.md").write_text(text)
    statuses = {step.name: step.status for step in report.steps}
    failures = {s.name: s.error for s in report.steps if s.status == "fail"}
    assert report.passed, failures
    expected = {
        "install-python",
        "sizes",
        "python-queries",
        "reverse-and-forward",
        "city-points",
        "vectors",
        "mcp",
        "skill",
        "plate-examples",
        "quality-gates",
    }
    assert {name for name, status in statuses.items() if status == "pass"} >= expected
    plates = report.step("plate-examples").details["splits"]["all"]
    assert plates == {"examples": 1, "top1": 1, "top3": 1, "candidates": 1}
    if driver.node() is not None:
        assert statuses["install-node"] == statuses["cross-client"] == "pass"
        assert report.step("cross-client").details["identical"] > 0
    assert report.step("skill").details["examples"] >= 30
    assert report.step("install-python").details["update"]["update_available"] is False
    assert "| core |" in text and "## Reverse and forward checks" in text
    assert "## Plate examples" in text
    gates = report.step("quality-gates").details
    assert gates["advisory"]["lost_cells"] == 42
    assert "## Lookups quality gates" in text
    checks = report.step("reverse-and-forward").details["checks"]
    assert checks["reverse"]["agreed"] == checks["reverse"]["applicable"] > 0


@pytest.mark.parametrize("value", ["", "x"])
def test_markdown_reports_a_failed_step(tmp_path: Path, value: str) -> None:
    report = driver.Report(driver.Settings(release=tmp_path, work=tmp_path))
    report.version = "2026.10"
    with driver.step(report, "install-python"):
        raise AssertionError(f"exit 4: corrupt{value}")
    assert not report.passed
    assert "| install-python | fail |" in driver.markdown(report)

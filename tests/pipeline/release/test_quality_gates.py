"""The lookups quality gates reach the dataset manifest and README."""

from pathlib import Path
from typing import Any

import pytest

from pipeline.config import Config, quality_policy
from pipeline.engines.artifacts import read_json
from pipeline.files import file_record
from pipeline.release import source
from pipeline.release.assemble import assemble
from pipeline.release.readme import quality
from pipeline.release.source import Snapshot, external
from pipeline.runtime.jsonio import write_json

from .fixtures import fixture

GATES: dict[str, Any] = {
    "blocking_scope": "reviewed",
    "reviewed_countries": ["MY", "SG"],
    "advisory": {
        "countries": 2,
        "boundary_losses": 3,
        "lost_cells": 1234,
        "footprint_failures": 1,
    },
}


def gated(
    snapshot: Snapshot, config: Config, gates: Any, report: bool = True
) -> Snapshot:
    """The snapshot's manifest with lookups gates and their quality.json record."""
    root = snapshot.root
    path = root / "quality.json"
    write_json(path, {"advisory_spatial_gates": {}, "gate_scope": {}})
    value = read_json(root / "manifest.json")
    value["quality_gates"] = gates
    value["verification_artifacts"] = [file_record(root, path)] if report else []
    write_json(root / "manifest.json", value)
    return external(root, config.h3)


def test_gates_and_their_report_reach_the_manifest_and_readme(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    snapshot = gated(snapshot, config, GATES)
    output = tmp_path / "dataset/2026.10"
    assemble(snapshot, output, config, guard, "identity")
    manifest = read_json(output / "manifest.json")
    report = file_record(snapshot.root, snapshot.root / "quality.json")
    assert manifest["quality_gates"] == {**GATES, "report": report}
    readme = (output / "README.md").read_text()
    section = readme.split("## Quality gates\n")[1].split("\n## ")[0]
    for text in (
        "`reviewed`",
        "2 reviewed countries (MY, SG)",
        "3 advisory boundary losses (1,234 cells)",
        "1 footprint failure in 2 unreviewed countries",
        "`advisory_spatial_gates`",
        "`gate_scope.by_country`",
        "`quality_gates.report`",
    ):
        assert text in section, text
    assert "`quality_gates`" in readme.split("## Versions and integrity")[1]


def test_an_input_without_gates_is_refused_by_path(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    manifest = snapshot.root / "manifest.json"
    value = read_json(manifest)
    del value["quality_gates"]
    write_json(manifest, value)
    output = tmp_path / "dataset/2026.10"
    with pytest.raises(ValueError, match="has no quality_gates") as error:
        assemble(external(snapshot.root, config.h3), output, config, guard, "x")
    assert str(manifest) in str(error.value)
    assert not output.parent.exists() or not any(output.parent.iterdir())


def test_a_release_read_back_keeps_its_report(tmp_path: Path) -> None:
    snapshot, config, _ = fixture(tmp_path)
    record = {"path": "work/quality.json", "size": 2, "sha256": "0" * 64}
    released = gated(snapshot, config, {**GATES, "report": record}, report=False)
    assert released.quality_gates == {**GATES, "report": record}


@pytest.mark.parametrize(
    "change",
    [
        {"blocking_scope": "some"},
        {"reviewed_countries": "MY"},
        {"advisory": {"countries": 1}},
        {"advisory": {**GATES["advisory"], "lost_cells": "1"}},
    ],
)
def test_malformed_gates_are_refused(tmp_path: Path, change: dict[str, Any]) -> None:
    snapshot, config, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="quality gates"):
        _ = gated(snapshot, config, {**GATES, **change}).quality_gates


def test_gates_without_their_quality_report_are_refused(tmp_path: Path) -> None:
    snapshot, config, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match=r"one quality\.json record"):
        _ = gated(snapshot, config, GATES, report=False).quality_gates


def test_wording_for_each_scope() -> None:
    clean = {**GATES, "advisory": dict.fromkeys(GATES["advisory"], 0)}
    text = quality(clean)
    assert "0 advisory boundary losses (0 cells)" in text
    assert "0 footprint failures in 0 unreviewed countries" in text
    every = quality({**clean, "blocking_scope": "all", "reviewed_countries": []})
    assert "`all`" in every and "in every country" in every
    assert "unreviewed" not in every
    # Only the committed documentation renders without gates.
    assert "null" not in quality(None) and "predates" in quality(None)


def test_release_scopes_are_the_quality_policy_scopes() -> None:
    assert source.SCOPES == quality_policy.SCOPES

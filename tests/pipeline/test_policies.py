"""The YAML split preserves every resolved country policy and its review binding."""

import json
import shutil
from pathlib import Path

import pytest

from pipeline.config import policies
from pipeline.runtime.jsonio import digest

FIXTURES = Path(__file__).parents[1] / "fixtures/policies"


def test_reconcile_policy_has_identical_canonical_fingerprint() -> None:
    expected = json.loads((FIXTURES / "reconcile.json").read_bytes())
    assert policies.reconcile() == expected
    assert digest(policies.reconcile()) == digest(expected)


def test_every_country_policy_has_identical_resolved_fingerprint() -> None:
    expected = json.loads((FIXTURES / "cities.json").read_bytes())
    assert policies.cities() == expected
    assert digest(policies.cities()) == digest(expected)
    # All possible country keys also exercise the no-override case.
    for first in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        for second in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            cc = first + second
            resolved = {
                **expected,
                "countries": {cc: expected["countries"][cc]}
                if cc in expected["countries"]
                else {},
            }
            assert digest(policies.cities(country=cc)) == digest(resolved)


def test_country_edit_changes_only_its_policy(tmp_path: Path) -> None:
    directory = tmp_path / "cities"
    shutil.copytree(policies.DIRECTORY / "cities", directory)
    before = {cc: digest(policies.cities(directory, cc)) for cc in ["BE", "IN", "CN"]}
    path = directory / "CN.yaml"
    path.write_text(path.read_text().replace("priority: 5", "priority: 6"))
    after = {cc: digest(policies.cities(directory, cc)) for cc in before}
    assert before["CN"] != after["CN"]
    assert before["BE"] == after["BE"]
    assert before["IN"] == after["IN"]


def test_policy_validation_names_unknown_field(tmp_path: Path) -> None:
    path = tmp_path / "reconcile.yaml"
    path.write_text("nearest_typo: 50000\n")
    with pytest.raises(ValueError, match="nearest_typo"):
        policies.reconcile(path)


def test_retained_review_binds_exact_policy_and_rejects_policy_edits() -> None:
    from pipeline.config.reviews import load

    path = policies.DIRECTORY.parent / "reviews/cities-pilot.yaml"
    original = policies.cities()
    review = load(path, original)
    assert review.minimum_dev_correct == 38
    assert len(review.boundary_exceptions) == 2
    original["countries"]["CN"]["footprints"][0]["priority"] += 1
    with pytest.raises(ValueError, match=r"cities-pilot\.yaml"):
        load(path, original)

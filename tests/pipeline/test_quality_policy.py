"""The lookups quality policy names which countries' findings block."""

from pathlib import Path

import pytest

from pipeline.config.quality_policy import load
from pipeline.runtime.fingerprints import REPOSITORY


def test_repository_policy_blocks_on_reviewed_countries() -> None:
    policy = load(REPOSITORY / "config/policies/quality.yaml")
    assert policy == {"gates": {"blocking_scope": "reviewed"}}


def test_scope_defaults_to_reviewed(tmp_path: Path) -> None:
    path = tmp_path / "quality.yaml"
    path.write_text("gates: {}\n")
    assert load(path) == {"gates": {"blocking_scope": "reviewed"}}


@pytest.mark.parametrize(
    "text",
    ["gates: {blocking_scope: pilot}\n", "gates: {blocking: all}\n", "scope: all\n"],
)
def test_unknown_scope_or_field_is_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "quality.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="quality policy"):
        load(path)

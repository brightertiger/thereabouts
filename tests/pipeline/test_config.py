"""Reject configuration mistakes before any writable workspace is opened."""

from pathlib import Path

import pytest

from pipeline.cli import main
from pipeline.config import load


@pytest.mark.parametrize(
    "override",
    [
        "resources.workres=2",
        "resources.workers=several",
        "resources.workers=0",
        "resources.disk_floor=4999999999",
        "paths.raw=/tmp/raw",
        "paths.work=../other",
        "h3.block_resolution=9",
        "h3.block_resolution=2",
        "h3.cell_resolution=9",
        "engines.runtime.reader_cache_entries=0",
        "engines.countries=[ZZ,ZZ]",
        "engines.blocks=[invalid]",
        "resources.poll_seconds=0",
        "resources.ledger_timeout_seconds=-1",
        "storage.local=plain",
        "engines.city_review=config/reviews/missing.yaml",
    ],
)
def test_invalid_configuration_has_no_side_effects(
    tmp_path: Path, override: str
) -> None:
    root = tmp_path / "never-created"
    assert main(["run", "--root", str(root), override]) == 2
    assert not root.exists()


def test_profile_and_overrides_have_documented_precedence() -> None:
    result = load(profile="vm", overrides=["paths.root=sample", "resources.workers=2"])
    assert result.paths.root == "sample"
    assert result.resources.workers == 2
    assert result.resources.duckdb_memory == "1GB"


def test_profile_cannot_escape_config_directory() -> None:
    with pytest.raises(ValueError, match="Profile"):
        load(profile="../outside")

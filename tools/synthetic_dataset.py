"""Copy the committed synthetic Parquet inputs for isolated writer tests."""

import shutil
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/datasets/core-synthetic"


def golden(root: Path) -> tuple[Path, Path]:
    """Reuse the independently frozen legacy inputs, never expected result JSON."""
    if root.resolve() != FIXTURE.resolve():
        shutil.copytree(FIXTURE, root, dirs_exist_ok=True)
    return root / "golden/manifest.json", root / "release.json"

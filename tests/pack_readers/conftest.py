"""Reader fixtures copy immutable committed client packs."""

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def serving(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1] / "fixtures/serving"
    return Path(shutil.copytree(source, tmp_path / "pack"))

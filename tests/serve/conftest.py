from pathlib import Path

import pytest

from pipeline.engines.serving.export import export

from .fixtures import golden


@pytest.fixture
def snapshot(tmp_path: Path) -> tuple[Path, Path]:
    return golden(tmp_path / "input")


@pytest.fixture
def serving(snapshot: tuple[Path, Path], tmp_path: Path) -> Path:
    return export(*snapshot, tmp_path / "pack", shard_bytes=1024)

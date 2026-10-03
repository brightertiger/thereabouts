from pathlib import Path

import pytest

from pipeline.engines.serving.export import export

from .fixtures import snapshot


@pytest.fixture(scope="session")
def code_packs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("code-packs")
    manifest, release = snapshot(root / "input")
    return {
        family: export(
            manifest, release, root / family, family=family, shard_bytes=2048
        )
        for family in ("reverse", "postal", "airports")
    }

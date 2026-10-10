"""An upload needs ledger records for exactly the bytes being published."""

from pathlib import Path

import pytest

from pipeline.config import Config
from pipeline.release import proof
from pipeline.release.assemble import assemble
from pipeline.release_command import main
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe

from .fixtures import fixture


def release(root: Path) -> Config:
    """An assembled dataset plus a core archive, index and acceptance report."""
    snapshot, config, guard = fixture(root)
    assemble(snapshot, root / "dataset/2026.10", config, guard, "identity")
    packs = root / "packs/2026.10"
    packs.mkdir(parents=True)
    (packs / "core.tar.zst").write_bytes(b"archive")
    write_json(packs / "index.json", {"format": 3})
    write_json(packs / "acceptance/core.json", {"passed": True})
    config.release.packs.families = ["core"]
    return config


def record(
    root: Path, config: Config, stage: str, unit: str, paths: list[Path]
) -> None:
    with Ledger(
        root,
        root / config.paths.ledger,
        readonly=False,
        timeout=config.resources.ledger_timeout_seconds,
    ) as ledger:
        ledger.register(Recipe(stage, unit))
        ledger.complete(stage, unit, "0" * 64, paths)


def complete(root: Path, config: Config) -> None:
    packs = root / "packs/2026.10"
    record(root, config, "dataset", "2026.10", [root / "dataset/2026.10/manifest.json"])
    record(
        root,
        config,
        "packs",
        "2026.10/core",
        [packs / "acceptance/core.json", packs / "core.tar.zst"],
    )
    record(root, config, "packs", "2026.10/index", [packs / "index.json"])


def test_records_for_the_exact_bytes_admit_the_upload(tmp_path: Path) -> None:
    config = release(tmp_path)
    with pytest.raises(ValueError, match="no pipeline ledger"):
        proof.verify(tmp_path, config, "2026.10")
    complete(tmp_path, config)
    proof.verify(tmp_path, config, "2026.10")


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ("dataset/2026.10/manifest.json", "dataset/2026.10 differs"),
        ("packs/2026.10/core.tar.zst", "packs/2026.10/core differs"),
        ("packs/2026.10/acceptance/core.json", "packs/2026.10/core differs"),
        ("packs/2026.10/index.json", "packs/2026.10/index differs"),
    ],
)
def test_bytes_other_than_the_recorded_ones_are_refused(
    tmp_path: Path, changed: str, message: str
) -> None:
    config = release(tmp_path)
    complete(tmp_path, config)
    path = tmp_path / changed
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match=message):
        proof.verify(tmp_path, config, "2026.10")


def test_a_missing_gate_record_is_refused(tmp_path: Path) -> None:
    config = release(tmp_path)
    record(
        tmp_path,
        config,
        "dataset",
        "2026.10",
        [tmp_path / "dataset/2026.10/manifest.json"],
    )
    with pytest.raises(ValueError, match=r"no completed packs/2026\.10/core"):
        proof.verify(tmp_path, config, "2026.10")


def test_release_upload_refuses_without_proof(tmp_path: Path) -> None:
    release(tmp_path)
    with pytest.raises(ValueError, match="no pipeline ledger"):
        main(
            [
                "upload",
                "--root",
                str(tmp_path),
                "--version",
                "2026.10",
                "release.packs.families=[core]",
                f"storage.s3_release={(tmp_path / 'remote').as_uri()}",
                "--dry-run",
            ]
        )
    assert not (tmp_path / "remote").exists()

"""Read-only targets and stale backups fail before any workspace mutation."""

from pathlib import Path

import pytest

from pipeline.cli import main
from pipeline.migration.preflight import check_writable

from .helpers import legacy_workspace


def files(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_apply_permission_preflight_precedes_lock_backup_and_journal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "data"
    legacy_workspace(root)
    target = root / "normalized/ghsl"
    before = files(root)
    target.chmod(0o555)
    try:
        assert main(["migrate", "--root", str(root)]) == 2
        message = capsys.readouterr().out
        assert f"chmod u+w {target}" in message
        assert f"chmod a-w {target}" in message
        assert files(root) == before
    finally:
        target.chmod(0o755)


def test_preflight_checks_existing_ancestor_of_new_evidence_directory(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "protected"
    parent.mkdir()
    parent.chmod(0o555)
    try:
        with pytest.raises(ValueError, match=r"chmod u\+w"):
            check_writable([parent / "new/hash/evidence.json"])
        assert list(parent.iterdir()) == []
    finally:
        parent.chmod(0o755)


def test_existing_unrelated_backup_is_not_silently_kept(tmp_path: Path) -> None:
    root = tmp_path / "data"
    legacy_workspace(root)
    (root / "work/ledger.pre-migration.sqlite3").write_bytes(b"unrelated backup")
    before = files(root)
    assert main(["migrate", "--root", str(root)]) == 2
    assert files(root) == before


def test_paths_step_cannot_recreate_a_lost_original_backup(tmp_path: Path) -> None:
    root = tmp_path / "data"
    legacy_workspace(root)
    options = ["--root", str(root), "--report", str(tmp_path / "report.json")]
    assert main(["migrate", "paths", *options]) == 0
    (root / "work/ledger.pre-migration.sqlite3").unlink()
    before = files(root)
    assert main(["migrate", "adopt", *options]) == 2
    assert files(root) == before

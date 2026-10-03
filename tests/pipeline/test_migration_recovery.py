"""Interrupted metadata changes roll back before migration can be retried."""

import importlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from pipeline.cli import main
from pipeline.config import load
from pipeline.migration.adoption import simulate
from pipeline.migration.apply import apply, recover
from pipeline.runtime.jsonio import atomic_output
from pipeline.runtime.ledger import Ledger
from pipeline.stages.registry import registry

from .helpers import legacy_workspace


def test_interrupt_between_json_and_ledger_is_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    path = legacy_workspace(root)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    module = importlib.import_module("pipeline.migration.apply")

    @contextmanager
    def interrupted(target: Path) -> Iterator[Path]:
        if target == path:
            raise OSError("simulated power loss before ledger publication")
        with atomic_output(target) as temporary:
            yield temporary

    with Ledger(root, path) as source:
        migration = simulate(root, source, load(), registry(load()))
        try:
            with monkeypatch.context() as patch:
                patch.setattr(module, "atomic_output", interrupted)
                with pytest.raises(OSError, match="power loss"):
                    apply(migration, source, path)
        finally:
            migration.context.ledger.close()
    assert (root / "work/migration/pending.json").exists()
    recover(root, path, root / "work")
    assert not (root / "work/migration/pending.json").exists()
    assert all(p.read_bytes() == data for p, data in before.items())
    assert (
        main(
            ["migrate", "--root", str(root), "--report", str(tmp_path / "report.json")]
        )
        == 0
    )


def test_separate_paths_and_adopt_steps_and_idempotence(tmp_path: Path) -> None:
    root = tmp_path / "data"
    path = legacy_workspace(root)
    common = ["--root", str(root), "--report", str(tmp_path / "report.json")]
    assert main(["migrate", "paths", *common]) == 0
    with Ledger(root, path) as ledger:
        assert not ledger.migrated
        assert all(
            not output.path.startswith("/")
            for r in ledger.records()
            for output in r.outputs
        )
    assert main(["migrate", "adopt", *common]) == 0
    before = {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in root.rglob("*")
        if p.is_file()
    }
    assert main(["migrate", *common]) == 0
    assert before == {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in root.rglob("*")
        if p.is_file()
    }
    assert main(["migrate", "check", *common]) == 0


def test_check_and_rejected_invalidation_do_not_initialize_legacy_ledger(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    path = legacy_workspace(root)
    before = path.read_bytes()
    assert main(["migrate", "check", "--root", str(root)]) == 2
    assert main(["invalidate", "normalize", "--root", str(root)]) == 2
    assert path.read_bytes() == before
    assert not (root / "work/pipeline.lock").exists()

"""Completion and planned work survive a move and intentional invalidation."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from pipeline.runtime.ledger import Ledger, read_connection
from pipeline.runtime.records import Recipe
from pipeline.runtime.verification import Verifier


def test_move_and_invalidate_preserve_the_recipe(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    artifact = root / "cells.parquet"
    artifact.write_bytes(b"content")
    with Ledger(root, root / "work/ledger.sqlite3", readonly=False) as ledger:
        with ledger.transaction():
            ledger.register(Recipe("cells", "one"))
        recorded = ledger.complete("cells", "one", "inputs", [artifact])
        assert recorded.outputs[0].path == "cells.parquet"
    moved = tmp_path / "moved"
    shutil.move(str(root), moved)
    with Ledger(moved, moved / "work/ledger.sqlite3", readonly=False) as ledger:
        record = ledger.get("cells", "one")
        assert record and Verifier(moved).completion_problem(record) is None
        (moved / "cells.parquet").write_bytes(b"corrupt")
        assert "corrupt" in str(Verifier(moved).completion_problem(record))
        assert ledger.invalidate("cells", ["one"]) == 1
        assert ledger.recipes() == [Recipe("cells", "one")]


def test_readonly_missing_ledger_does_not_initialize_workspace(tmp_path: Path) -> None:
    root = tmp_path / "absent"
    with Ledger(root, root / "work/ledger.sqlite3") as ledger:
        assert list(ledger.records()) == []
        with pytest.raises(ValueError, match="read-only"):
            ledger.invalidate("cells")
    assert not root.exists()


def test_readonly_ledger_creates_no_sidecars(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    with Ledger(tmp_path, path, readonly=False):
        pass
    before = {
        p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.iterdir()
    }
    with Ledger(tmp_path, path) as ledger:
        assert ledger.recipes() == []
    assert before == {
        p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.iterdir()
    }


def test_active_wal_is_not_silently_ignored(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE example (value TEXT)")
        db.commit()
        with pytest.raises(ValueError, match="active WAL"):
            read_connection(path)
    finally:
        db.close()


def test_escape_and_unpublished_output_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"payload")
    (root / "link").symlink_to(outside)
    (root / "unfinished.part").write_bytes(b"partial")
    with Ledger(root, None, readonly=False) as ledger:
        for path in (outside, root / "link", root / "unfinished.part"):
            with pytest.raises(ValueError):
                ledger.complete("cells", "bad", "inputs", [path])

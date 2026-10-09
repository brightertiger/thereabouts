"""Helpers shared by engines and adapters behave like the copies they replace."""

import sqlite3
from pathlib import Path

import pytest

from pipeline.errors import (
    ArtifactIntegrityError,
    ConfigError,
    InputIntegrityError,
    PolicyViolation,
)
from pipeline.runtime.jsonio import file_record, sha256_file
from pipeline.runtime.sqlite import sqlite_readonly


def test_file_record_is_root_relative(tmp_path: Path) -> None:
    path = tmp_path / "normalized/geonames/places/part-0.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"rows")
    assert file_record(tmp_path, path) == {
        "path": "normalized/geonames/places/part-0.parquet",
        "size": 4,
        "sha256": sha256_file(path),
    }
    with pytest.raises(ValueError):
        file_record(tmp_path / "normalized", tmp_path / "outside.json")


def test_sqlite_readonly_refuses_writes_and_sets_the_cache(tmp_path: Path) -> None:
    path = tmp_path / "artifact.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE t(x)")
    db = sqlite_readonly(path, 2048)
    try:
        assert db.execute("PRAGMA cache_size").fetchone() == (-2048,)
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO t VALUES(1)")
    finally:
        db.close()
    default = sqlite_readonly(path)
    try:
        assert default.execute("SELECT count(*) FROM t").fetchone() == (0,)
    finally:
        default.close()


def test_domain_errors_remain_value_errors() -> None:
    for error in (
        ConfigError,
        InputIntegrityError,
        PolicyViolation,
        ArtifactIntegrityError,
    ):
        assert issubclass(error, ValueError)

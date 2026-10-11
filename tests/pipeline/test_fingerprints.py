"""Output identity follows only explicitly declared production inputs."""

import sqlite3
from pathlib import Path

import pytest

from pipeline.runtime import fingerprints
from pipeline.runtime.code import code_hashes
from pipeline.runtime.fingerprints import identity


def test_identity_is_portable_and_excludes_tests_and_client_code(
    tmp_path: Path,
) -> None:
    first, moved = tmp_path / "first", tmp_path / "moved"
    for root in (first, moved):
        (root / "pipeline/cells").mkdir(parents=True)
        (root / "pipeline/cells/build.py").write_text("def build(): return 1\n")

    def calculate(root: Path, **options: object) -> str:
        return identity(
            [root / "pipeline/cells"],
            config={"resolution": 8, **options},
            pins={"release": "pinned"},
            native={"h3": "pinned"},
            cell_format=1,
            repository=root,
        )

    baseline = calculate(first)
    assert baseline == calculate(moved)
    for name in ("tests", "eval", "docs", "clients/python/thereabouts"):
        directory = first / name
        directory.mkdir(parents=True)
        (directory / "fixture.py").write_text("changed = True\n")
    (first / "pipeline/cells/probes.json").write_text('{"fixture": 1}')
    assert calculate(first) == baseline
    assert calculate(first, country="BE") != baseline
    (first / "pipeline/cells/build.py").write_text("def build(): return 2\n")
    assert calculate(first) != baseline


def test_pins_native_versions_and_explicit_cell_format_change_identity(
    tmp_path: Path,
) -> None:
    package = tmp_path / "pipeline/cells"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Cells."""\n')

    def calculate(pin: str, native: str, format_version: int) -> str:
        return identity(
            [package],
            config={},
            pins={"source": pin},
            native={"duckdb": native},
            cell_format=format_version,
            repository=tmp_path,
        )

    baseline = calculate("a", "a", 1)
    assert (
        len(
            {
                baseline,
                calculate("b", "a", 1),
                calculate("a", "b", 1),
                calculate("a", "a", 2),
            }
        )
        == 4
    )


def test_non_python_package_file_is_not_an_empty_code_identity(tmp_path: Path) -> None:
    path = tmp_path / "pipeline/config.txt"
    path.parent.mkdir()
    path.write_text("not Python")
    with pytest.raises(ValueError, match="must be Python"):
        identity([path], config={}, pins={}, native={}, repository=tmp_path)


def test_transitive_relative_inline_imports_and_exclusions(tmp_path: Path) -> None:
    sources = {
        "pipeline/stage.py": "from .engine import build\n",
        "pipeline/engine/__init__.py": "from .geometry import build\n",
        "pipeline/engine/geometry.py": (
            "def build():\n from pipeline.shared import rule\n"
        ),
        "pipeline/shared.py": "from pipeline.runtime.ledger import Ledger\nrule = 1\n",
        "pipeline/runtime/ledger.py": "class Ledger: pass\n",
    }
    for name, source in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    entry = tmp_path / "pipeline/stage.py"
    before = code_hashes([entry], tmp_path)
    assert set(before) == set(sources) - {"pipeline/runtime/ledger.py"}
    shared = tmp_path / "pipeline/shared.py"
    shared.write_text(shared.read_text().replace("rule = 1", "rule = 2"))
    assert code_hashes([entry], tmp_path) != before


def test_city_closure_covers_geometry_and_source_closure_covers_storage() -> None:
    root = Path(__file__).parents[2]
    city = code_hashes([root / "pipeline/stages/cities.py"], root)
    assert "pipeline/engines/cells/windows.py" in city
    assert "pipeline/engines/cells/offshore.py" in city
    assert "pipeline/stages/reconcile.py" in city
    source = code_hashes([root / "pipeline/stages/sources.py"], root)
    assert "pipeline/storage/objects.py" in source
    assert "pipeline/pins/models.py" in source


def test_entry_module_hashes_parent_initializers_without_imports(
    tmp_path: Path,
) -> None:
    package = tmp_path / "pipeline/engine"
    package.mkdir(parents=True)
    entry = package / "build.py"
    entry.write_text("value = 1\n")
    initializer = package / "__init__.py"
    initializer.write_text("rule = 1\n")
    root_initializer = package.parent / "__init__.py"
    root_initializer.write_text("root_rule = 1\n")
    before = code_hashes([entry], tmp_path)
    assert len(before) == 3
    initializer.write_text("rule = 2\n")
    assert code_hashes([entry], tmp_path) != before


def test_sqlite_runtime_version_is_an_explicit_native_identity_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text("package = []\n")
    before = fingerprints.native_versions(["sqlite3"], lock)
    monkeypatch.setattr(sqlite3, "sqlite_version", "different-native")
    assert fingerprints.native_versions(["sqlite3"], lock) != before

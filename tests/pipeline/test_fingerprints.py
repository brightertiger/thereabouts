"""Output identity follows only explicitly declared production inputs."""

from pathlib import Path

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
    for name in ("tests", "eval", "docs", "src/thereabouts"):
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

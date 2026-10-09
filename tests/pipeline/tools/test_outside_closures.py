"""Command-line and documentation tools never enter a stage identity."""

from pipeline.config import load
from pipeline.runtime.fingerprints import REPOSITORY, closures

TOOLS = (
    "pipeline/cli.py",
    "pipeline/release_command.py",
    "pipeline/tools/__init__.py",
    "pipeline/tools/dictionary.py",
    "pipeline/tools/dictionary_markdown.py",
    "pipeline/tools/dictionary_surface.py",
)


def test_tools_live_outside_release_and_every_stage_closure() -> None:
    hashed = set().union(*closures(load()).values())
    for path in TOOLS:
        assert (REPOSITORY / path).is_file(), path
        assert path not in hashed, path
    assert not (REPOSITORY / "pipeline/release/command.py").exists()
    assert not list((REPOSITORY / "pipeline/release").glob("dictionary*.py"))

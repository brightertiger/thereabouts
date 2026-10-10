"""Command-line entry points never enter a stage identity."""

from pipeline.config import load
from pipeline.runtime.fingerprints import REPOSITORY, closures

COMMANDS = ("pipeline/cli.py", "pipeline/release_command.py")


def test_commands_live_outside_release_and_every_stage_closure() -> None:
    hashed = set().union(*closures(load()).values())
    for path in COMMANDS:
        assert (REPOSITORY / path).is_file(), path
        assert path not in hashed, path
    assert not (REPOSITORY / "pipeline/release/command.py").exists()

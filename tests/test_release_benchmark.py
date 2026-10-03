"""Release measurements stay local by default and survive staging cleanup."""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from benchmarks import release_path
from pipeline.runtime import resources


def test_scan_tolerates_retired_staging_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kept = tmp_path / "kept"
    gone = tmp_path / "records-00000.bin"
    kept.write_bytes(b"kept")
    gone.write_bytes(b"staging")

    def walk(
        _root: Path, *, followlinks: bool
    ) -> Iterator[tuple[str, list[str], list[str]]]:
        assert not followlinks
        names = [kept.name, gone.name]
        gone.unlink()
        yield str(tmp_path), [], names

    monkeypatch.setattr(os, "walk", walk)
    assert resources.workspace_bytes(tmp_path) == len(b"kept")


def test_tracked_measurement_requires_explicit_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release_path, "ROOT", tmp_path)
    tracked = tmp_path / "docs/CLIENT_RELEASE_MEASUREMENTS.json"
    tracked.parent.mkdir()
    tracked.write_text('{"existing": true}\n')
    output = tmp_path / "output"
    output.mkdir()
    report = {"seconds": 1.25}
    release_path.record(report, output, write=False)
    assert json.loads(tracked.read_text()) == {"existing": True}
    assert json.loads((output / "measurements.json").read_text()) == report
    release_path.record(report, output, write=True)
    assert json.loads(tracked.read_text()) == report


@pytest.mark.parametrize(
    "arguments", [["benchmarks/release_path.py"], ["-m", "benchmarks.release_path"]]
)
def test_script_and_module_entrypoints(arguments: list[str]) -> None:
    process = subprocess.run(
        [sys.executable, *arguments, "--help"],
        cwd=release_path.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert "--write" in process.stdout

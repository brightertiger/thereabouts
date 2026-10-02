"""Controller stops and explicit retention of completed evaluation evidence."""

import sys
from pathlib import Path

import pytest

from build_data.acquire.artifacts import read_json
from build_data.rebuild_golden import Controller, main


def invoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *arguments: str
) -> list[str]:
    stages: list[str] = []

    def upstream(self: Controller, sample_gate: Path | None, workers: int) -> None:
        stages.append("upstream")

    def run(self: Controller, stage: str, module: str, *arguments: str) -> None:
        stages.append(stage)

    monkeypatch.setattr(Controller, "upstream", upstream)
    monkeypatch.setattr(Controller, "run", run)
    monkeypatch.setattr(
        sys, "argv", ["rebuild", "--data-dir", str(tmp_path), *arguments]
    )
    main()
    return stages


def test_base_stop_never_runs_pilot_or_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert invoke(tmp_path, monkeypatch, "--through", "base") == ["upstream"]
    assert read_json(tmp_path / "work/rebuild/run.json")["stage"] == "base"


def test_retained_development_is_not_rescored_or_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "work/v2-dev.json"
    report.parent.mkdir()
    report.write_text('{"retained": true}\n')
    stamp = report.stat().st_mtime_ns
    assert invoke(
        tmp_path, monkeypatch, "--through", "pilot", "--reuse-development"
    ) == ["upstream", "city-pilot", "pilot-quality", "pilot-blocks"]
    assert report.read_text() == '{"retained": true}\n'
    assert report.stat().st_mtime_ns == stamp


def test_development_retention_requires_prior_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemExit, match="2"):
        invoke(tmp_path, monkeypatch, "--through", "pilot", "--reuse-development")
    assert not (tmp_path / "work/rebuild/run.json").exists()


def test_default_still_runs_development(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "pilot-dev" in invoke(tmp_path, monkeypatch, "--through", "pilot")

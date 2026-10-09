"""Each stage's identity closure covers every pipeline file its units execute."""

import sys
import threading
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import CodeType
from typing import Any

import pytest

from pipeline.runtime.code import EXCLUDED
from pipeline.runtime.fingerprints import REPOSITORY, adapter_hashes, closures
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.runner import run
from pipeline.stages.contract import Context, Unit
from pipeline.stages.geographic import GeographicStage

from .geographic_fixtures import build, geographic_graph, source_receipts
from .sources.fixtures import source_context
from .test_recorded_content import boundary_payloads

if sys.version_info < (3, 12):
    pytest.skip("sys.monitoring needs Python 3.12", allow_module_level=True)

PIPELINE = f"{REPOSITORY}/pipeline/"
TOOL = 3
Run = Callable[[Context, Unit], list[Path]]


class Executed:
    """Pipeline files whose code starts while a stage's unit runs, per stage.

    Each code location reports once, then is disabled; every unit restarts
    the events, so a function shared by two stages is seen by both.
    """

    def __init__(self) -> None:
        self.current = threading.local()
        self.files: dict[str, set[str]] = defaultdict(set)

    def start(self, code: CodeType, offset: int) -> Any:
        stage = getattr(self.current, "stage", None)
        if stage is None:
            return None
        if code.co_filename.startswith(PIPELINE):
            self.files[stage].add(code.co_filename.removeprefix(f"{REPOSITORY}/"))
        return sys.monitoring.DISABLE

    def wrap(self, name: str, run: Run) -> Run:
        def observed(ctx: Context, unit: Unit) -> list[Path]:
            sys.monitoring.restart_events()
            self.current.stage = name
            try:
                return run(ctx, unit)
            finally:
                self.current.stage = None

        return observed


@contextmanager
def executed() -> Iterator[Executed]:
    record = Executed()
    events = sys.monitoring.events
    sys.monitoring.use_tool_id(TOOL, "stage-closures")
    try:
        sys.monitoring.register_callback(TOOL, events.PY_START, record.start)
        sys.monitoring.set_events(TOOL, events.PY_START)
        yield record
    finally:
        sys.monitoring.set_events(TOOL, 0)
        sys.monitoring.register_callback(TOOL, events.PY_START, None)
        sys.monitoring.free_tool_id(TOOL)


def uncovered(files: set[str], closure: set[str]) -> set[str]:
    return {
        name
        for name in files - closure
        if not any(name.startswith(item) for item in EXCLUDED)
    }


def test_geographic_closures_cover_what_their_units_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger, executed() as record:
        ctx, normalized = source_receipts(tmp_path, ledger, wide=True)
        stages = geographic_graph(ctx, normalized)
        for stage in stages:
            if isinstance(stage, GeographicStage):
                monkeypatch.setattr(
                    stage, "execute", record.wrap(stage.name, stage.execute)
                )
        build(ctx, stages)
        dump = closures(ctx.config)
    assert set(record.files) == {
        "reconcile",
        "cells",
        "cities",
        "normalize_cells",
        "lookups",
    }
    assert "pipeline/engines/cells/build.py" in record.files["cells"]
    assert "pipeline/engines/store/areas.py" in record.files["reconcile"]
    for name, files in record.files.items():
        assert not uncovered(files, set(dump[name])), name


def test_source_closures_cover_downloads_and_normalizers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger, executed() as record:
        runtime, source, stages = source_context(
            tmp_path, ledger, "geoboundaries", boundary_payloads(tmp_path)
        )
        source.pin.metadata["country_reference"] = {"GBR": {"alpha2": "GB"}}
        for stage in stages:
            monkeypatch.setattr(stage, "run", record.wrap(stage.name, stage.run))
        run(runtime, stages)
        dump = closures(runtime.config)
    adapter = set(adapter_hashes(source.settings.adapter))
    assert set(record.files) == {"download", "normalize"}
    assert "pipeline/sources/geoboundaries/convert.py" in record.files["normalize"]
    assert "pipeline/sources/download.py" in record.files["download"]
    assert not uncovered(record.files["download"], set(dump["download"]))
    assert not uncovered(record.files["normalize"], set(dump["normalize"]) | adapter)

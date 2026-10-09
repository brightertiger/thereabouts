"""Executable source discovery, resumability and relative paths after a move."""

import json
import shutil
from dataclasses import fields, replace
from pathlib import Path

import pytest

from pipeline.pins.workspace import from_manifest
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import plan
from pipeline.runtime.runner import run
from pipeline.runtime.verification import Verifier
from pipeline.stages.sources import adapter_context

from .fixtures import source_context


def test_completed_sources_plan_current_after_moving_workspace(tmp_path: Path) -> None:
    root = tmp_path / "original"
    path = root / "work/ledger.sqlite3"
    with Ledger(root, path, readonly=False, timeout=30) as ledger:
        runtime, source, stages = source_context(
            root,
            ledger,
            "airports",
            {
                "airports.csv": (
                    b"ident,name,latitude_deg,longitude_deg,iso_country\n"
                    b"TEST,Example,50.85,4.35,BE\n",
                    {},
                ),
            },
        )
        assert {unit.key for stage in stages for unit in stage.units(runtime)} == {
            ("download", "airports"),
            ("normalize", "airports"),
        }
        assert run(runtime, stages) == {"completed": 2, "skipped": 0}
        manifest = json.loads((source.normalized / "manifest.json").read_bytes())
        assert from_manifest(root, manifest) == source.pin
    moved = tmp_path / "moved"
    shutil.move(root, moved)
    with Ledger(moved, moved / "work/ledger.sqlite3") as ledger:
        ctx = replace(runtime, root=moved, ledger=ledger, verifier=Verifier(moved))
        decisions = plan(ctx, stages)
        assert len(decisions) == 2 and all(d.state == "current" for d in decisions)
        assert all(
            not output.path.startswith("/")
            for record in ledger.records()
            for output in record.outputs
        )


def test_adapters_receive_only_the_narrow_source_context(tmp_path: Path) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        runtime, source, stages = source_context(
            tmp_path, ledger, "airports", {"airports.csv": (b"payload", {})}
        )
        assert [field.name for field in fields(source)] == [
            "settings",
            "pin",
            "inputs_hash",
            "root",
            "paths",
            "grid",
            "guard",
            "storage",
            "log",
        ]
        assert (source.grid, source.guard, source.storage, source.log) == (
            runtime.config.h3,
            runtime.guard,
            runtime.storage,
            runtime.log,
        )
        assert source.work == tmp_path / "work/airports"
        # The plate adapters still spell the unit's hash `ctx.unit.inputs_hash`.
        assert source.unit.inputs_hash == source.inputs_hash
        unit = stages[1].units(runtime)[0]
        with pytest.raises(ValueError, match="read-only"):
            adapter_context(
                replace(runtime, readonly=True), source.settings, source.pin, unit
            )

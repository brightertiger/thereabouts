"""Executable source discovery, resumability and relative paths after a move."""

import shutil
from dataclasses import replace
from pathlib import Path

from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import plan
from pipeline.runtime.runner import run
from pipeline.runtime.verification import Verifier

from .fixtures import source_context


def test_completed_sources_plan_current_after_moving_workspace(tmp_path: Path) -> None:
    root = tmp_path / "original"
    path = root / "work/ledger.sqlite3"
    with Ledger(root, path, readonly=False, timeout=30) as ledger:
        source, stages = source_context(
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
        assert {
            unit.key for stage in stages for unit in stage.units(source.runtime)
        } == {
            ("download", "airports"),
            ("normalize", "airports"),
        }
        assert run(source.runtime, stages) == {"completed": 2, "skipped": 0}
    moved = tmp_path / "moved"
    shutil.move(root, moved)
    with Ledger(moved, moved / "work/ledger.sqlite3") as ledger:
        ctx = replace(
            source.runtime, root=moved, ledger=ledger, verifier=Verifier(moved)
        )
        decisions = plan(ctx, stages)
        assert len(decisions) == 2 and all(d.state == "current" for d in decisions)
        assert all(
            not output.path.startswith("/")
            for record in ledger.records()
            for output in record.outputs
        )

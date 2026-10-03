"""Auxiliary extraction/index outputs stay tracked and must verify like source data."""

import json
import sqlite3
from pathlib import Path

import pytest

from pipeline.config import load
from pipeline.migration.adoption import simulate
from pipeline.runtime.ledger import Ledger
from pipeline.stages.registry import registry

from .helpers import legacy_workspace, record


@pytest.mark.parametrize(
    "stage", ["geonames.extract", "geonames.index", "overture.index"]
)
def test_auxiliary_is_retained_and_missing_or_corrupt_bytes_refuse_adoption(
    tmp_path: Path, stage: str
) -> None:
    source = stage.partition(".")[0]
    root = tmp_path / "data"
    path = legacy_workspace(root, source=source)
    auxiliary = root / f"work/{source}/auxiliary"
    auxiliary.parent.mkdir(parents=True)
    auxiliary.write_bytes(b"small retained auxiliary")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO units VALUES (?,?,?,?,?,?)",
            (
                stage,
                "index",
                "old-inputs",
                json.dumps([record(auxiliary)]),
                "{}",
                "old",
            ),
        )
    config = load()
    with Ledger(root, path) as ledger:
        migration = simulate(root, ledger, config, registry(config))
        try:
            completion = migration.context.ledger.get("normalize", source)
            assert completion is not None
            assert auxiliary.relative_to(root).as_posix() in {
                output.path for output in completion.outputs
            }
            assert migration.report["dropped_rows"] == 0
            assert migration.report["adopted_units"] == 2
        finally:
            migration.context.ledger.close()
        auxiliary.write_bytes(b"bad")
        with pytest.raises(ValueError, match="Cannot adopt"):
            simulate(root, ledger, config, registry(config))
        auxiliary.unlink()
        with pytest.raises(ValueError, match="output missing"):
            simulate(root, ledger, config, registry(config))

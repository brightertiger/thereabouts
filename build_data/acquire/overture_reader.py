"""Overture reader."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pyarrow.parquet as pq

from . import Ledger, Workspace, fingerprint, sha256_file
from .overture import SOURCE
from .runtime import source_budget


def _raw_hash(workspace: Workspace, obj: dict[str, Any]) -> str:
    source = workspace.raw(SOURCE) / obj["relative_path"]
    checksum = sha256_file(source)
    receipt = json.loads(source.with_name(source.name + ".download.json").read_text())
    if source.stat().st_size != obj["size"] or checksum != receipt["verified_sha256"]:
        raise ValueError(f"Raw object integrity failed: {source}")
    return checksum


def _entity_index(
    workspace: Workspace, inventory: dict[str, Any]
) -> sqlite3.Connection:
    """Small disk-backed identity/parent lookup; no global Python graph."""
    path = workspace.work / SOURCE / "entities.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    objects = [obj for obj in inventory["objects"] if obj["type"] == "division"]
    inputs = {obj["key"]: _raw_hash(workspace, obj) for obj in objects}
    inputs_hash = fingerprint({"raw_inputs": inputs, "builder": "overture-index-1"})
    ledger = Ledger(workspace.ledger_path)
    complete = ledger.is_complete("overture.index", "entities", inputs_hash)
    if not complete:
        # An index is expendable only after its pinned raw inputs are verified.
        path.unlink(missing_ok=True)
        path.with_name(path.name + "-journal").unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA cache_size=-32768")
    db.execute(
        "CREATE TABLE IF NOT EXISTS entities"
        "(id TEXT PRIMARY KEY, parent TEXT) WITHOUT ROWID"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS indexed(unit TEXT PRIMARY KEY, checksum TEXT)"
    )
    for obj in objects:
        source = workspace.raw(SOURCE) / obj["relative_path"]
        checksum = inputs[obj["key"]]
        unit = obj["key"]
        previous = db.execute(
            "SELECT checksum FROM indexed WHERE unit=?", (unit,)
        ).fetchone()
        if previous:
            if previous[0] != checksum:
                raise ValueError("Entity index belongs to different raw bytes")
            continue
        source_budget(workspace, SOURCE, 1_000_000_000)
        with db, pq.ParquetFile(source) as parquet:
            for batch in parquet.iter_batches(
                batch_size=4096, columns=["id", "parent_division_id"], use_threads=False
            ):
                db.executemany(
                    "INSERT INTO entities VALUES (?,?)",
                    (
                        (row["id"], row["parent_division_id"])
                        for row in batch.to_pylist()
                    ),
                )
            db.execute("INSERT INTO indexed VALUES (?,?)", (unit, checksum))
    if not complete:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Entity index failed SQLite integrity verification")
        ledger.complete("overture.index", "entities", inputs_hash, [path])
    return db

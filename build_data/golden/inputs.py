"""Read only committed country checkpoints, including a world run in progress."""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import read_json, verify_files
from build_data.acquire.io import fingerprint
from build_data.acquire.ledger import read_units
from build_data.reconcile.common import Row


@lru_cache(maxsize=50_000)
def _verify(path: str, size: int, sha256: str, modified: int) -> None:
    # Cache only within this process. A new command rehashes everything; a
    # watch pass rehashes any file whose stat or expected digest changed.
    verify_files([{"path": path, "size": size, "sha256": sha256}])


def verify_record(record: Row) -> None:
    stat = Path(record["path"]).stat()
    if stat.st_size != record["size"]:
        raise ValueError(f"Artifact size mismatch: {record['path']}")
    _verify(record["path"], record["size"], record["sha256"], stat.st_mtime_ns)


@dataclass
class Inputs:
    countries: dict[str, Row]
    land: Row
    policy: Row
    sources: Row
    builder: str
    expected: set[str] | None = None

    @property
    def paths(self) -> dict[str, Path]:
        return {cc: Path(r["path"]) for cc, r in self.countries.items()}

    @property
    def identity(self) -> str:
        return fingerprint(
            {"sources": self.sources, "policy": self.policy, "builder": self.builder}
        )


def discover(workspace: Workspace, *, verify: bool = True) -> Inputs:
    ledger = Ledger(workspace.ledger_path)
    # Reconciliation replaces its manifest immediately before committing the
    # ledger record. Permit that short publication window without taking its lock.
    for _ in range(30):
        manifest = read_json(workspace.root / "reconciled" / "manifest.json")
        if ledger.is_complete("reconcile.manifest", "current", fingerprint(manifest)):
            break
        time.sleep(0.1)
    else:
        raise ValueError("Reconciled snapshot has no verified manifest commit")
    source_hash = fingerprint(manifest["sources"])
    countries = {}
    if verify:
        print("verify committed reconciled countries and land", flush=True)
    for unit in read_units(workspace.ledger_path, "reconcile.country"):
        cc = unit["unit_id"]
        expected = fingerprint(
            {
                "inputs": source_hash,
                "policy": manifest["policy"],
                "builder": manifest["builder"],
                "country": cc,
            }
        )
        if unit["inputs_hash"] != expected:
            continue
        record = unit["outputs"][0]
        path = Path(record["path"])
        if not path.exists() or path.stat().st_size != record["size"]:
            raise ValueError(f"Missing committed country: {cc}")
        if verify:
            verify_record(record)
        countries[cc] = record
    if verify:
        verify_record(manifest["land"])
        print(f"verified {len(countries)} countries and land", flush=True)
    return Inputs(
        countries,
        manifest["land"],
        manifest["policy"],
        manifest["sources"],
        manifest["builder"],
    )

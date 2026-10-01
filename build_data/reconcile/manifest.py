"""Atomic committed reconciled snapshots; status does no hashing or work."""

from __future__ import annotations

from pathlib import Path

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import file_record, read_json, verify_files
from build_data.acquire.io import fingerprint, write_json
from build_data.acquire.ledger import read_units

from .common import Row


def publish(
    workspace: Workspace,
    countries: dict[str, Path],
    land: Path,
    policy: Row,
    sources: Row,
    reports: dict[str, Path],
    builder: str,
) -> Row:
    ledger = Ledger(workspace.ledger_path)
    for stage, expected in (
        ("country", countries),
        ("land", {"world": land}),
        ("quality", reports),
    ):
        units = {
            r["unit_id"]: r
            for r in read_units(workspace.ledger_path, f"reconcile.{stage}")
        }
        for unit, output in expected.items():
            record = units.get(unit)
            if not record:
                raise ValueError(f"Missing {stage} checkpoint: {unit}")
            verified = ledger.completed_outputs(
                record["stage"], unit, record["inputs_hash"]
            )
            if verified is None or output.resolve() not in {
                p.resolve() for p in verified
            }:
                raise ValueError(f"Unverified {stage} artifact: {output}")
    manifest: Row = {
        "version": 1,
        "completed": True,
        "policy": policy,
        "builder": builder,
        "countries": {cc: file_record(p) for cc, p in countries.items()},
        "reports": {cc: file_record(p) for cc, p in reports.items()},
        "land": file_record(land),
        "sources": sources,
    }
    path = workspace.root / "reconciled" / "manifest.json"
    previous = read_json(path) if path.exists() else None
    write_json(path, manifest)
    Ledger(workspace.ledger_path).complete(
        "reconcile.manifest", "current", fingerprint(manifest), [path]
    )
    if previous:
        current = {
            Path(r["path"]).resolve()
            for r in [
                manifest["land"],
                *manifest["countries"].values(),
                *manifest["reports"].values(),
            ]
        }
        gate_path = path.parent / "pilot.json"
        if gate_path.exists():
            current.update(
                Path(p).resolve() for p in read_json(gate_path)["reports"].values()
            )
        old = [previous["land"], *previous["countries"].values()]
        if reports:
            old.extend(previous["reports"].values())
        for record in old:
            stale = Path(record["path"]).resolve()
            if stale not in current and stale.is_relative_to(path.parent.resolve()):
                stale.unlink(missing_ok=True)
    return manifest


def load(workspace: Workspace) -> Row:
    path = workspace.root / "reconciled" / "manifest.json"
    value = read_json(path)
    if value.get("version") != 1 or not Ledger(workspace.ledger_path).is_complete(
        "reconcile.manifest", "current", fingerprint(value)
    ):
        raise ValueError("Reconciled manifest is unsupported or uncommitted")
    if not value.get("completed", True):
        raise ValueError(
            "Reconciliation generation is still building; use country checkpoints"
        )
    verify_files(
        [value["land"], *value["countries"].values(), *value["reports"].values()]
    )
    return value


def status(workspace: Workspace) -> Row:
    stages = {
        stage: read_units(workspace.ledger_path, f"reconcile.{stage}")
        for stage in ("land", "extract", "links", "country", "quality")
    }
    units: Row = {}
    for stage, records in stages.items():
        units[stage] = [
            {
                "unit": r["unit_id"],
                "present": all(
                    Path(p["path"]).exists()
                    and Path(p["path"]).stat().st_size == p["size"]
                    for p in r["outputs"]
                ),
            }
            for r in records
        ]
    path = workspace.root / "reconciled" / "manifest.json"
    value = read_json(path) if path.exists() else {}
    committed = (
        any(
            r["inputs_hash"] == fingerprint(value)
            for r in read_units(workspace.ledger_path, "reconcile.manifest")
        )
        if value
        else False
    )
    return {
        "manifest_committed": committed,
        "countries": sorted(value.get("countries", {})),
        "checkpoints": units,
        "note": "Presence/size inspection only; run reconciliation to verify hashes.",
    }

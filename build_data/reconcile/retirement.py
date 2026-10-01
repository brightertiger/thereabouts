"""Disk-neutral country replacement, after verified checkpoint publication."""

from __future__ import annotations

from pathlib import Path

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, write_json
from build_data.acquire.ledger import read_units

from .common import Row


def begin(
    workspace: Workspace, policy: Row, sources: Row, land: Row, builder: str
) -> None:
    """Retire the old snapshot before replacing its immutable country files.

    Readers see a committed, explicitly incomplete new generation. Completed
    country checkpoints remain discoverable; an old manifest must never continue
    claiming completeness after one of its files has been retired.
    """
    path = workspace.root / "reconciled/manifest.json"
    previous = read_json(path) if path.exists() else None
    if previous and all(
        previous[key] == value
        for key, value in (
            ("builder", builder),
            ("policy", policy),
            ("sources", sources),
        )
    ):
        return
    if previous:
        archive = workspace.work / "reconcile/history" / f"{fingerprint(previous)}.json"
        write_json(archive, previous)
    snapshot = {
        "version": 1,
        "completed": False,
        "builder": builder,
        "policy": policy,
        "sources": sources,
        "land": land,
        "countries": {},
        "reports": {},
    }
    write_json(path, snapshot)
    Ledger(workspace.ledger_path).complete(
        "reconcile.manifest", "current", fingerprint(snapshot), [path]
    )


def retire_country(
    workspace: Workspace, country: str, output: Path, digest: str
) -> None:
    """Retry-safe cleanup; no old country or intermediate goes before verification."""
    ledger = Ledger(workspace.ledger_path)
    if ledger.completed_outputs("reconcile.country", country, digest) != (output,):
        raise ValueError(f"Cannot retire unverified country {country}")
    root = (workspace.root / "reconciled").resolve()
    # Scoped to this country's immutable output name. This also handles a crash
    # after the ledger was replaced but before stale output cleanup.
    for candidate in root.glob(f"*/{country}.sqlite"):
        if candidate.resolve() != output.resolve():
            candidate.unlink()
    work = (workspace.work / "reconcile").resolve()
    for stage in ("reconcile.extract", "reconcile.links"):
        for record in read_units(workspace.ledger_path, stage):
            if record["unit_id"] != country:
                continue
            for item in record["outputs"]:
                path = Path(item["path"]).resolve()
                if not path.is_relative_to(work):
                    raise ValueError(
                        f"Intermediate outside reconciliation workspace: {path}"
                    )
                path.unlink(missing_ok=True)

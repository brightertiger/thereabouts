"""Retire superseded reconciliation outputs only after a verified replacement."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.ledger import read_units

from .common import Row


def complete(
    workspace: Workspace,
    stage: str,
    unit: str,
    digest: str,
    outputs: Sequence[Path],
    metadata: Row | None = None,
) -> None:
    records = read_units(workspace.ledger_path, stage)
    previous = [
        Path(p["path"]) for r in records if r["unit_id"] == unit for p in r["outputs"]
    ]
    Ledger(workspace.ledger_path).complete(
        stage, unit, digest, outputs, metadata=metadata
    )
    protected = {p.resolve() for p in outputs}
    manifest = workspace.root / "reconciled" / "manifest.json"
    if manifest.exists():
        saved = read_json(manifest)
        protected.update(
            Path(r["path"]).resolve()
            for r in [
                saved["land"],
                *saved["countries"].values(),
                *saved["reports"].values(),
            ]
        )
    roots = [workspace.root / "reconciled", workspace.work / "reconcile"]
    for path in previous:
        path = path.resolve()
        if path not in protected and any(
            path.is_relative_to(r.resolve()) for r in roots
        ):
            path.unlink(missing_ok=True)

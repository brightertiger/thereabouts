"""Relative output records, scoped to stages regenerated with the golden dataset."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from build_data.acquire import Workspace
from build_data.acquire.artifacts import file_record
from build_data.acquire.io import sha256_file
from build_data.acquire.ledger import Ledger as SourceLedger
from build_data.acquire.ledger import read_units
from build_data.reconcile.common import Row

from .paths import resolved, stored


def units(workspace: Workspace, stage: str) -> list[Row]:
    return [
        resolved(row, workspace.root)
        for row in read_units(workspace.ledger_path, stage)
    ]


class Ledger(SourceLedger):
    """Use the existing schema and durability, leaving upstream records untouched."""

    def __init__(self, workspace: Workspace) -> None:
        self.root = workspace.root.resolve()
        super().__init__(workspace.ledger_path)

    def completed_outputs(
        self, stage: str, unit_id: str, inputs_hash: str
    ) -> tuple[Path, ...] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT outputs FROM units WHERE stage=? AND unit_id=? "
                "AND inputs_hash=?",
                (stage, unit_id, inputs_hash),
            ).fetchone()
        if row is None:
            return None
        paths = []
        for record in json.loads(row[0]):
            path = self.root / record["path"]
            try:
                if (
                    path.stat().st_size != record["size"]
                    or sha256_file(path) != record["sha256"]
                ):
                    return None
            except FileNotFoundError:
                return None
            paths.append(path)
        return tuple(paths)

    def complete(
        self,
        stage: str,
        unit_id: str,
        inputs_hash: str,
        outputs: Sequence[Path],
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        if not stage.startswith(("golden.", "normalize-cells.", "base-cells.")):
            raise ValueError("Relative ledger is only for rebuilt golden stages")
        records = []
        for path in outputs:
            if path.name.endswith(".part") or not path.is_file():
                raise ValueError(f"Output has not been published: {path}")
            records.append(stored(file_record(path), self.root))
        with self._connect() as db:
            db.execute(
                "INSERT INTO units VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(stage, unit_id) DO UPDATE SET "
                "inputs_hash=excluded.inputs_hash, outputs=excluded.outputs, "
                "metadata=excluded.metadata, completed_at=excluded.completed_at",
                (
                    stage,
                    unit_id,
                    inputs_hash,
                    json.dumps(records, sort_keys=True),
                    json.dumps(
                        stored(dict(metadata or {}), self.root),
                        sort_keys=True,
                        allow_nan=False,
                    ),
                    datetime.now(UTC).isoformat(),
                ),
            )

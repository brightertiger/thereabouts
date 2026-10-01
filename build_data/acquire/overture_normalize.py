"""Overture normalize."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq

from . import Ledger, Workspace, fingerprint
from .lifecycle import resume_source
from .overture import SOURCE
from .overture_reader import _entity_index, _raw_hash
from .overture_report import _finish
from .overture_settings import (
    BUILDER,
    POLICY,
    configuration,
)
from .overture_units import _unit
from .runtime import single_run


def run(workspace: Workspace) -> None:
    """Require full pinned raw acquisition, then checkpoint each source row group."""
    started = time.monotonic()
    with single_run(workspace, SOURCE), single_run(workspace, "geometry"):
        if resume_source(workspace, SOURCE, configuration()):
            return
        inventory = cast(
            dict[str, Any],
            json.loads((workspace.raw(SOURCE) / "inventory.json").read_text()),
        )
        ledger = Ledger(workspace.ledger_path)
        db = _entity_index(workspace, inventory)
        units: list[dict[str, str]] = []
        audits: list[Path] = []
        try:
            # Exercise polygon conversion early; the complete parent index exists.
            for obj in sorted(
                inventory["objects"], key=lambda item: item["type"] == "division"
            ):
                source = workspace.raw(SOURCE) / obj["relative_path"]
                checksum = _raw_hash(workspace, obj)
                with pq.ParquetFile(source) as parquet:
                    schema_hash = hashlib.sha256(
                        parquet.schema_arrow.serialize().to_pybytes()
                    ).hexdigest()
                    context = {
                        "source_url": obj["url"],
                        "source_release": inventory["source_release"],
                        "raw_sha256": checksum,
                        "etag": obj["etag"],
                        "schema_hash": schema_hash,
                        "retrieved_at": inventory["retrieved_at"],
                        "builder": BUILDER,
                        "policy": POLICY,
                        "entity_inputs": dict(
                            db.execute("SELECT unit, checksum FROM indexed")
                        ),
                    }
                    for group in range(parquet.num_row_groups):
                        inputs_hash = fingerprint(
                            {
                                **context,
                                "row_group": group,
                                **configuration(),
                            }
                        )
                        record, audit = _unit(
                            workspace,
                            obj,
                            parquet,
                            group,
                            context,
                            db,
                            ledger,
                            inputs_hash,
                        )
                        units.append(record)
                        audits.append(audit)
            _finish(workspace, inventory, units, audits, ledger, db, started)
        finally:
            db.close()

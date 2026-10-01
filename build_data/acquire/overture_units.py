"""Overture units."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import shapely

from . import Ledger, Workspace
from .geometry import GeometryError
from .io import write_json
from .overture import SOURCE
from .overture_areas import areas
from .overture_rows import RowRejectedError, names, place
from .overture_settings import BATCH_BYTES, PART_BYTES, SPOTS
from .runtime import peak_rss_bytes, resources, source_budget
from .schemas import Kind
from .writer import PartitionWriter


def _unit(
    workspace: Workspace,
    obj: dict[str, Any],
    parquet: pq.ParquetFile,
    group: int,
    context: dict[str, Any],
    db: sqlite3.Connection,
    ledger: Ledger,
    inputs_hash: str,
) -> tuple[dict[str, str], Path]:
    unit = f"{obj['key']}#row-group={group}"
    record = {
        "stage": "overture.normalize",
        "unit_id": unit,
        "inputs_hash": inputs_hash,
    }
    audit_path = (
        workspace.normalized(SOURCE)
        / "audits"
        / inputs_hash
        / (hashlib.sha256(unit.encode()).hexdigest() + ".json")
    )
    if ledger.is_complete(
        "overture.normalize", unit, inputs_hash
    ) and ledger.is_complete("overture.audit", unit, inputs_hash):
        return record, audit_path
    source_budget(
        workspace,
        SOURCE,
        min(parquet.metadata.row_group(group).total_byte_size * 3, 500_000_000),
    )
    started = time.monotonic()
    kind: Kind = "places" if obj["type"] == "division" else "areas"
    sink = PartitionWriter(
        workspace,
        SOURCE,
        kind,
        unit,
        inputs_hash,
        batch_bytes=BATCH_BYTES,
        part_bytes=PART_BYTES,
    )
    aliases = PartitionWriter(
        workspace,
        SOURCE,
        "names",
        unit,
        inputs_hash,
        batch_bytes=BATCH_BYTES,
        part_bytes=PART_BYTES,
    )
    stats: Counter[str] = Counter()
    subtypes: Counter[str] = Counter()
    rejects: list[dict[str, Any]] = []
    spots: dict[str, list[dict[str, Any]]] = {name: [] for name in SPOTS}
    for batch in parquet.iter_batches(
        batch_size=128 if kind == "places" else 8, row_groups=[group], use_threads=False
    ):
        if peak_rss_bytes() > 2_800_000_000:
            raise MemoryError("Overture RSS exceeded 2.8 GB; unit remains unfinished")
        for row in batch.to_pylist():
            stats["input_rows"] += 1
            subtypes[row["subtype"]] += 1
            row_context = {
                **context,
                "row_group": group,
                "row_in_group": stats["input_rows"] - 1,
            }
            before = sink.count
            try:
                if kind == "places":
                    converted = place(row, row_context)
                    converted_aliases = list(names(row, row_context))
                    sink.add(converted)
                    stats["valid_input"] += 1
                    for alias in converted_aliases:
                        aliases.add(alias)
                else:
                    entity = db.execute(
                        "SELECT parent FROM entities WHERE id=?", (row["division_id"],)
                    ).fetchone()
                    if entity is None:
                        stats["missing_division_ids"] += 1
                    for area in areas(
                        row, row_context, entity[0] if entity else None, stats, spots
                    ):
                        sink.add(area)
                stats["accepted_features"] += 1
            except (
                RowRejectedError,
                GeometryError,
                shapely.errors.GEOSException,
            ) as error:
                if sink.count != before:
                    raise ValueError(
                        f"Partial feature conversion aborted unit: {row['id']}"
                    ) from error
                rejects.append(
                    {
                        "id": row["id"],
                        "row_in_group": stats["input_rows"] - 1,
                        "reason": str(error),
                    }
                )
                stats["rejected_features"] += 1
    expected = parquet.metadata.row_group(group).num_rows
    if (
        stats["input_rows"] != expected
        or stats["accepted_features"] + stats["rejected_features"] != expected
    ):
        raise ValueError("Row-group source count mismatch")
    outputs = sink.finish() + aliases.finish()
    audit = {
        "unit_id": unit,
        "inputs_hash": inputs_hash,
        "kind": kind,
        "counts": dict(stats),
        "subtypes": dict(subtypes),
        "rejects": rejects,
        "output_rows": {kind: sink.count, "names": aliases.count},
        "spot_checks": spots,
        **resources(started),
    }
    write_json(audit_path, audit)
    ledger.complete("overture.audit", unit, inputs_hash, [audit_path])
    ledger.complete("overture.normalize", unit, inputs_hash, outputs, metadata=audit)
    for output in outputs:
        for temporary in output.parent.glob(f".{output.name}.*.part"):
            temporary.unlink()
    print(
        f"NORMALIZED {obj['type']} group {group}: "
        f"{stats['input_rows']} input, {sink.count} {kind}, {aliases.count} names, "
        f"{len(rejects)} rejects ({time.monotonic() - started:.1f}s)",
        flush=True,
    )
    return record, audit_path

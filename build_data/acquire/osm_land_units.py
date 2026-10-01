"""Osm land units."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import shapefile
import shapely

from . import SCHEMAS, Ledger, Workspace
from .io import write_json
from .osm_land import RELEASE, SOURCE
from .osm_land_reader import _feature
from .osm_land_rows import _row, _spot_hits
from .osm_land_settings import (
    MAX_UNIT_BYTES,
    MAX_UNIT_RECORDS,
    RSS_LIMIT_BYTES,
    SPOT_CHECKS,
)
from .runtime import peak_rss_bytes, source_budget
from .writer import PartitionWriter


def _run_unit(
    workspace: Workspace,
    reader: Any,
    inventory: dict[str, Any],
    source_hash: str,
    unit_id: str,
    records: list[int],
    extent: list[float],
    inputs_hash: str,
    ledger: Ledger,
) -> tuple[Path, Path]:
    source_budget(workspace, SOURCE, MAX_UNIT_BYTES * 3)
    if peak_rss_bytes() > RSS_LIMIT_BYTES:
        raise MemoryError("OSM land process exceeded its 3 GB RSS budget")
    rows: list[dict[str, object]] = []
    repairs: list[dict[str, object]] = []
    for ordinal in records:
        try:
            row, repair = _row(
                *_feature(reader, ordinal), ordinal, inventory, source_hash
            )
        except (
            ValueError,
            shapely.errors.GEOSException,
            shapefile.ShapefileException,
        ) as exc:
            write_json(
                workspace.work / "osm_land-rejection.json",
                {
                    "source_release": RELEASE,
                    "unit_id": unit_id,
                    "record_index": ordinal,
                    "error": str(exc),
                    "rejected_records": 1,
                    "status": "blocked; no manifest published",
                },
            )
            raise
        rows.append(row)
        if repair is not None:
            repairs.append(repair)
    table = pa.Table.from_pylist(rows, schema=SCHEMAS["areas"])
    hits: dict[str, list[str]] = {name: [] for name in SPOT_CHECKS}
    _spot_hits(table, hits)
    writer = PartitionWriter(
        workspace,
        SOURCE,
        "areas",
        unit_id,
        inputs_hash,
        batch_bytes=32_000_000,
        batch_rows=MAX_UNIT_RECORDS,
    )
    for row in rows:
        writer.add(row)
    [path] = writer.finish()
    audit = path.with_suffix(".audit.json")
    write_json(
        audit,
        {
            "unit_id": unit_id,
            "rows": len(records),
            "record_indices": records,
            "extent": extent,
            "invalid_input_count": len(repairs),
            "repairs": repairs,
            "rejected_records": 0,
            "invalid_output_count": 0,
            "spot_hits": hits,
            "decoded_bytes": table.nbytes,
        },
    )
    ledger.complete(
        f"{SOURCE}.normalize",
        unit_id,
        inputs_hash,
        [path, audit],
        metadata={
            "rows": len(records),
            "rejected_records": 0,
            "repaired_records": len(repairs),
            "extent": extent,
        },
    )
    return path, audit

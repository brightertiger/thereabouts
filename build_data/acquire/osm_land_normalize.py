"""Osm land normalize."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq
import shapefile
import shapely

from . import SCHEMA_HASHES, Ledger, Workspace, fingerprint, sha256_file
from .lifecycle import resume_source
from .osm_land import (
    ARCHIVE,
    BUILDER_VERSION,
    POLICY_VERSION,
    SOURCE,
    _inventory,
    _snapshot,
)
from .osm_land_reader import _build_index, _publisher_notice, _units
from .osm_land_report import _publish_manifest
from .osm_land_settings import (
    GRID_DEGREES,
    MAX_SOURCE_RECORD_BYTES,
    MAX_UNIT_BYTES,
    MAX_UNIT_RECORDS,
    SPOT_CHECKS,
    configuration,
)
from .osm_land_units import _run_unit
from .runtime import peak_rss_bytes, single_run, source_budget


def normalize(workspace: Workspace) -> None:
    """Resume deterministic byte-capped spatial units through direct SHX access."""
    started = time.monotonic()
    with single_run(workspace, SOURCE), single_run(workspace, "geometry"):
        if resume_source(workspace, SOURCE, configuration()):
            return
        inventory = _inventory(workspace)
        snapshot = _snapshot(workspace)
        verification = cast(
            dict[str, Any],
            json.loads((snapshot / "download-verification.json").read_text()),
        )
        ledger = Ledger(workspace.ledger_path)
        archive_hash = verification["archive_sha256"]
        download_hash = fingerprint(
            {"inventory": inventory, "sha256": archive_hash, "builder": BUILDER_VERSION}
        )
        if not ledger.is_complete(f"{SOURCE}.download", ARCHIVE, download_hash):
            raise ValueError("Raw archive verification failed; rerun download")
        shps = list((snapshot / "extracted").rglob("*.shp"))
        if len(shps) != 1:
            raise ValueError("Expected exactly one polygon shapefile")
        shp = shps[0]
        hashes = {
            suffix: sha256_file(shp.with_suffix(suffix))
            for suffix in (".shp", ".shx", ".dbf", ".prj")
        }
        for member in verification["zip_members"]:
            member_hash = fingerprint(
                {
                    "archive_sha256": archive_hash,
                    "member": member["name"],
                    "crc32": member["crc32"],
                    "size": member["size"],
                    "builder": BUILDER_VERSION,
                }
            )
            if not ledger.is_complete(
                f"{SOURCE}.download", f"extract/{member['name']}", member_hash
            ):
                raise ValueError("Extracted member verification failed; rerun download")
        projection = shp.with_suffix(".prj").read_text()
        if (
            'GEOGCS["GCS_WGS_1984"' not in projection
            or 'UNIT["Degree"' not in projection
        ):
            raise ValueError(f"Unexpected source CRS: {projection}")
        parameters = {
            "sha256s": hashes,
            "archive_sha256": archive_hash,
            "inventory": inventory,
            "builder": BUILDER_VERSION,
            "policy": POLICY_VERSION,
            "schema": SCHEMA_HASHES["areas"],
            "grid_degrees": GRID_DEGREES,
            "max_records": MAX_UNIT_RECORDS,
            "max_unit_bytes": MAX_UNIT_BYTES,
            "max_source_record_bytes": MAX_SOURCE_RECORD_BYTES,
            "shapely_version": shapely.__version__,
            "pyshp_version": shapefile.__version__,
        }
        index_hash = fingerprint(parameters)
        index = workspace.normalized(SOURCE) / f"index-{index_hash}.sqlite3"
        if not ledger.is_complete(
            f"{SOURCE}.index", "spatial-record-index", index_hash
        ):
            source_budget(workspace, SOURCE, 200_000_000)
            count = _build_index(shp, index)
            ledger.complete(
                f"{SOURCE}.index",
                "spatial-record-index",
                index_hash,
                [index],
                metadata={"rows": count},
            )
        counts = {
            "rows": 0,
            "invalid_input_count": 0,
            "repaired_records": 0,
            "rejected_records": 0,
            "invalid_output_count": 0,
            "output_bytes": 0,
        }
        hits: dict[str, list[str]] = {name: [] for name in SPOT_CHECKS}
        units: list[dict[str, str]] = []
        auxiliary: list[Path] = []
        with sqlite3.connect(index) as db:
            source_count = int(db.execute("SELECT count(*) FROM records").fetchone()[0])
        with shapefile.Reader(str(shp)) as reader:
            if reader.numRecords != source_count:
                raise ValueError("DBF and SHX record counts differ")
            notice = _publisher_notice(shp, source_count)
            for unit_id, records, extent in _units(index):
                inputs_hash = fingerprint(
                    {**parameters, "unit_id": unit_id, "records": records}
                )
                outputs = ledger.completed_outputs(
                    f"{SOURCE}.normalize", unit_id, inputs_hash
                )
                if outputs is None:
                    outputs = _run_unit(
                        workspace,
                        reader,
                        inventory,
                        hashes[".shp"],
                        unit_id,
                        records,
                        extent,
                        inputs_hash,
                        ledger,
                    )
                path, audit_path = outputs
                with pq.ParquetFile(path) as parquet:
                    if parquet.metadata.num_rows != len(records):
                        raise ValueError(f"Output count mismatch: {unit_id}")
                audit = json.loads(audit_path.read_text())
                counts["rows"] += audit["rows"]
                counts["invalid_input_count"] += audit["invalid_input_count"]
                counts["repaired_records"] += len(audit["repairs"])
                counts["output_bytes"] += path.stat().st_size
                for name, identifiers in audit["spot_hits"].items():
                    hits[name].extend(identifiers)
                auxiliary.append(audit_path)
                units.append(
                    {
                        "stage": f"{SOURCE}.normalize",
                        "unit_id": unit_id,
                        "inputs_hash": inputs_hash,
                    }
                )
                if len(units) % 100 == 0:
                    print(
                        f"OSM land: {len(units)} units, {counts['rows']:,} rows, "
                        f"peak RSS {peak_rss_bytes():,} bytes",
                        flush=True,
                    )
        _publish_manifest(
            workspace,
            units,
            counts,
            source_count,
            hits,
            auxiliary,
            started,
            index,
            notice,
        )
        print(
            f"OSM land normalization complete: {counts}, "
            f"{time.monotonic() - started:.1f}s",
            flush=True,
        )

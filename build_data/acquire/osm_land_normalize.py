"""Bounded SHX-indexed normalization; original split polygons remain separate."""

from __future__ import annotations

import json
import math
import re
import resource
import sqlite3
import struct
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, BinaryIO, cast

import pyarrow as pa
import pyarrow.parquet as pq
import shapefile
import shapely
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from . import (
    SCHEMA_HASHES,
    SCHEMAS,
    Ledger,
    Workspace,
    atomic_output,
    fingerprint,
    sha256_file,
    write_partition,
)
from .io import write_json
from .osm_land import (
    ARCHIVE,
    BUILDER_VERSION,
    LICENSE_URL,
    POLICY_VERSION,
    RELEASE,
    SOURCE,
    SOURCE_URL,
    _budget,
    _inventory,
    _ledger,
    _snapshot,
    _source_lock,
)

GRID_DEGREES = 10
MAX_UNIT_RECORDS = 1000
MAX_UNIT_BYTES = 8_000_000
MAX_SOURCE_RECORD_BYTES = 6_000_000
RSS_LIMIT_BYTES = 3_000_000_000
# Longitude, latitude, expected physical-land containment.
SPOT_CHECKS = {
    "Lagos": (3.3947, 6.4541, True),
    "Hong Kong Central": (114.1582, 22.2819, True),
    "Monaco": (7.4246, 43.7384, True),
    "Mombasa": (39.6682, -4.0435, True),
    "mid-Atlantic": (-30.0, 0.0, False),
    "Antarctic interior": (0.0, -89.0, True),
    "dateline east land": (179.5, 68.0, True),
    "dateline west land": (-179.5, 68.0, True),
}


def _rss() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    value = stream.read(size)
    if len(value) != size:
        raise ValueError("Truncated shapefile record/header")
    return value


def _shape_header(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = _read_exact(stream, 100)
    code = struct.unpack_from(">i", header)[0]
    length = struct.unpack_from(">i", header, 24)[0] * 2
    version, kind = struct.unpack_from("<ii", header, 28)
    if code != 9994 or version != 1000 or kind != 5 or length != path.stat().st_size:
        raise ValueError(f"Invalid 2D polygon shapefile header: {path}")
    return length, kind


def _records(shp: Path) -> Iterator[tuple[int, int, int, float, float, float, float]]:
    """Read only index entries and record bboxes, never whole-world geometry."""
    shp_size, _ = _shape_header(shp)
    shx = shp.with_suffix(".shx")
    shx_size, _ = _shape_header(shx)
    if (shx_size - 100) % 8:
        raise ValueError("SHX index is not a whole number of records")
    previous_end = 100
    with shx.open("rb") as index, shp.open("rb") as geometry:
        index.seek(100)
        for ordinal in range((shx_size - 100) // 8):
            offset_words, length_words = struct.unpack(">ii", _read_exact(index, 8))
            offset, length = offset_words * 2, length_words * 2
            if offset != previous_end or length < 44 or offset + 8 + length > shp_size:
                raise ValueError(f"Broken SHX offset/length at record {ordinal}")
            if length > MAX_SOURCE_RECORD_BYTES:
                raise ValueError(
                    f"Record {ordinal} exceeds geometry limit; isolate it first"
                )
            geometry.seek(offset)
            record_number, record_words = struct.unpack(">ii", _read_exact(geometry, 8))
            if record_words != length_words or record_number != ordinal + 1:
                raise ValueError(f"SHP/SHX record disagreement at {ordinal}")
            kind = struct.unpack("<i", _read_exact(geometry, 4))[0]
            if kind != 5:
                raise ValueError(
                    f"Unexpected shape type {kind} at {ordinal}; no record discarded"
                )
            bounds = struct.unpack("<4d", _read_exact(geometry, 32))
            xmin, ymin, xmax, ymax = bounds
            if not (
                all(math.isfinite(v) for v in bounds)
                and -180 <= xmin <= xmax <= 180
                and -90 <= ymin <= ymax <= 90
            ):
                raise ValueError(f"Invalid source bbox at {ordinal}: {bounds}")
            yield ordinal, offset, length, xmin, ymin, xmax, ymax
            previous_end = offset + 8 + length
    if previous_end != shp_size:
        raise ValueError("SHP contains bytes/records absent from SHX")


def _validate_index(path: Path) -> None:
    with sqlite3.connect(path) as db:
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Invalid OSM spatial work index")


def _build_index(shp: Path, destination: Path) -> int:
    with (
        atomic_output(destination, _validate_index) as temporary,
        sqlite3.connect(temporary) as db,
    ):
        db.execute(
            "CREATE TABLE records (ordinal INTEGER PRIMARY KEY, offset INTEGER, "
            "bytes INTEGER, xmin REAL, ymin REAL, xmax REAL, ymax REAL, "
            "gx INTEGER, gy INTEGER)"
        )
        count = 0
        for record in _records(shp):
            gx, gy = (
                math.floor(record[3] / GRID_DEGREES),
                math.floor(record[4] / GRID_DEGREES),
            )
            db.execute(
                "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*record, gx, gy),
            )
            count += 1
        db.execute("CREATE INDEX spatial_order ON records (gx, gy, ordinal)")
    return count


def _units(index: Path) -> Iterator[tuple[str, list[int], list[float]]]:
    with sqlite3.connect(index) as db:
        records: list[int] = []
        size, sequence = 0, 0
        cell: tuple[int, int] | None = None
        extent = [180.0, 90.0, -180.0, -90.0]
        for ordinal, length, xmin, ymin, xmax, ymax, gx, gy in db.execute(
            "SELECT ordinal, bytes, xmin, ymin, xmax, ymax, gx, gy "
            "FROM records ORDER BY gx, gy, ordinal"
        ):
            current = (gx, gy)
            if records and (
                current != cell
                or len(records) == MAX_UNIT_RECORDS
                or size + length > MAX_UNIT_BYTES
            ):
                assert cell is not None
                yield f"grid/{cell[0]}/{cell[1]}/{sequence:05d}", records, extent
                sequence = sequence + 1 if current == cell else 0
                records, size = [], 0
                extent = [180.0, 90.0, -180.0, -90.0]
            cell = current
            records.append(ordinal)
            size += length
            extent = [
                min(extent[0], xmin),
                min(extent[1], ymin),
                max(extent[2], xmax),
                max(extent[3], ymax),
            ]
        if records and cell is not None:
            yield f"grid/{cell[0]}/{cell[1]}/{sequence:05d}", records, extent


def _row(
    reader: Any, ordinal: int, inventory: dict[str, Any], input_hash: str
) -> tuple[dict[str, object], dict[str, object] | None]:
    source_shape = reader.shape(ordinal)
    attributes = reader.record(ordinal)
    if attributes is None:
        raise ValueError(
            f"Deleted/missing DBF record {ordinal}; retained in raw archive"
        )
    geometry: BaseGeometry = shape(source_shape.__geo_interface__)
    audit = None
    if not geometry.is_valid:
        reason = str(shapely.is_valid_reason(geometry))
        geometry = shapely.make_valid(geometry)
        audit = {
            "record_index": ordinal,
            "invalid_reason": reason,
            "repair": "shapely.make_valid",
        }
    if (
        geometry.is_empty
        or geometry.geom_type not in ("Polygon", "MultiPolygon")
        or not geometry.is_valid
    ):
        raise ValueError(
            f"Record {ordinal} cannot normalize losslessly: {geometry.geom_type}"
        )
    source_id = f"shp-record:{ordinal}"
    provenance = {
        "source_url": SOURCE_URL,
        "license_url": LICENSE_URL,
        "attribution": inventory["attribution"],
        "retrieved_at": inventory["retrieved_at"],
        "input_sha256": input_hash,
        "shp_record_index": ordinal,
        "source_attributes": attributes.as_dict(),
        "shp_part_starts": list(source_shape.parts),
        "source_shape_type": source_shape.shapeType,
        "coordinate_transform": "none",
        "simplification": "none",
        "repair": audit,
        "edge_identity": "source_id + WKB polygon/ring/segment ordinal",
        "boundary_semantics": (
            "overlapping source split edges; boundary is NOT necessarily coastline"
        ),
        "coastline_reconstruction": (
            "retain only edge portions exposed outside interiors of neighboring "
            "land polygons; handle +/-180 and polar closure separately"
        ),
        "inland_water": "not subtracted by source",
    }
    xmin, ymin, xmax, ymax = geometry.bounds
    return {
        "source": SOURCE,
        "source_id": source_id,
        "entity_id": source_id,
        "kind": "land",
        "subtype": "split_land_polygon",
        "geometry": geometry.wkb,
        "xmin": xmin,
        "ymin": ymin,
        "xmax": xmax,
        "ymax": ymax,
        "is_land": True,
        "is_territorial": False,
        "source_release": RELEASE,
        "license": "ODbL-1.0",
        "provenance": json.dumps(provenance, sort_keys=True, allow_nan=False),
    }, audit


def _spot_hits(table: pa.Table, hits: dict[str, list[str]]) -> None:
    for row in table.select(
        ["source_id", "geometry", "xmin", "ymin", "xmax", "ymax"]
    ).to_pylist():
        for name, (x, y, _) in SPOT_CHECKS.items():
            if (
                row["xmin"] <= x <= row["xmax"]
                and row["ymin"] <= y <= row["ymax"]
                and shapely.from_wkb(row["geometry"]).covers(Point(x, y))
            ):
                hits[name].append(row["source_id"])


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
    _budget(workspace, MAX_UNIT_BYTES * 3)
    if _rss() > RSS_LIMIT_BYTES:
        raise MemoryError("OSM land process exceeded its 3 GB RSS budget")
    rows: list[dict[str, object]] = []
    repairs: list[dict[str, object]] = []
    for ordinal in records:
        try:
            row, repair = _row(reader, ordinal, inventory, source_hash)
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
    path = workspace.partition(SOURCE, "areas", unit_id, inputs_hash)
    write_partition(path, "areas", [table])
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


def _auxiliary(paths: Sequence[Path]) -> list[dict[str, object]]:
    return [
        {"path": str(p.resolve()), "size": p.stat().st_size, "sha256": sha256_file(p)}
        for p in paths
    ]


def _publisher_notice(shp: Path, source_count: int) -> dict[str, object]:
    notice = shp.parent / "README.txt"
    text = notice.read_text(encoding="utf-8")
    count = re.search(r"(\d+) Polygon features", text)
    date = re.search(r"Date of the data used is (\S+)", text)
    if count is None or date is None:
        raise ValueError("Publisher README lacks its feature count or data date")
    published_count = int(count[1])
    if published_count != source_count:
        raise ValueError("Publisher README, SHX and DBF counts disagree")
    return {
        "polygon_features": published_count,
        "data_date": date[1],
        "path": str(notice.resolve()),
        "sha256": sha256_file(notice),
    }


def _publish_manifest(
    workspace: Workspace,
    units: list[dict[str, str]],
    counts: dict[str, int],
    source_count: int,
    hits: dict[str, list[str]],
    auxiliary: list[Path],
    started: float,
    index: Path,
    notice: dict[str, object],
) -> None:
    if counts["rows"] != source_count:
        raise ValueError(
            f"Output count {counts['rows']} differs from source {source_count}"
        )
    checks = {
        name: {
            "longitude": x,
            "latitude": y,
            "expected_land": expected,
            "actual_land": bool(hits[name]),
            "source_ids": hits[name],
            "passed": bool(hits[name]) == expected,
        }
        for name, (x, y, expected) in SPOT_CHECKS.items()
    }
    latest_report = workspace.normalized(SOURCE) / "verification.json"
    previous = json.loads(latest_report.read_text()) if latest_report.exists() else {}
    if previous.get("input_index", str(index)) != str(index):
        previous = {}
    elapsed = time.monotonic() - started
    report_data: dict[str, object] = {
        **counts,
        "source_dbf_records": source_count,
        "source_shx_records": source_count,
        "input_index": str(index),
        "publisher_notice": notice,
        "publisher_count_basis": "ZIP README, SHX index entries and DBF header",
        "spot_checks": checks,
        "peak_rss_bytes": _rss(),
        "elapsed_seconds": elapsed,
        "first_run_elapsed_seconds": previous.get(
            "first_run_elapsed_seconds", previous.get("elapsed_seconds", elapsed)
        ),
        "peak_rss_all_runs_bytes": max(
            previous.get("peak_rss_all_runs_bytes", previous.get("peak_rss_bytes", 0)),
            _rss(),
        ),
        "kind_counts": {"land": counts["rows"]},
        "subtype_counts": {"split_land_polygon": counts["rows"]},
        "partition_count": len(units),
        "dropped_records": 0,
        "coastline_edges_classified": False,
        "spatial_partitioning": (
            "10-degree lower-left source-bbox buckets; "
            "intact source tiles may extend beyond bucket"
        ),
    }
    # Keep manifest-referenced reports immutable, including across failed reruns.
    report = workspace.normalized(SOURCE) / (
        f"verification-{fingerprint(report_data)}.json"
    )
    write_json(report, report_data)
    write_json(latest_report, report_data)
    if not all(item["passed"] for item in checks.values()):
        raise ValueError(f"OSM land spot checks failed; see {report}")
    write_json(
        workspace.normalized(SOURCE) / "manifest.json",
        {
            "schema_version": "1",
            "source": SOURCE,
            "source_release": RELEASE,
            "source_data_date": notice["data_date"],
            "units": units,
            "auxiliary": _auxiliary([*auxiliary, report, index]),
            "builder_version": BUILDER_VERSION,
            "policy_version": POLICY_VERSION,
            "edge_policy": (
                "Original split overlaps retained. Reconciliation must cancel "
                "interior split edges before coastal-distance calculations."
            ),
        },
    )


def normalize(workspace: Workspace) -> None:
    """Resume deterministic byte-capped spatial units through direct SHX access."""
    started = time.monotonic()
    with _source_lock(workspace):
        inventory = _inventory(workspace)
        snapshot = _snapshot(workspace)
        verification = cast(
            dict[str, Any],
            json.loads((snapshot / "download-verification.json").read_text()),
        )
        ledger = _ledger(workspace)
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
            _budget(workspace, 200_000_000)
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
                        f"peak RSS {_rss():,} bytes",
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

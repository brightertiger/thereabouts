"""Osm land reader."""

from __future__ import annotations

import math
import re
import sqlite3
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from . import atomic_output, sha256_file
from .geometry import check_bounds
from .osm_land_settings import (
    GRID_DEGREES,
    MAX_SOURCE_RECORD_BYTES,
    MAX_UNIT_BYTES,
    MAX_UNIT_RECORDS,
)


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
            check_bounds(bounds)
            xmin, ymin, xmax, ymax = bounds
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


def _feature(reader: Any, ordinal: int) -> tuple[BaseGeometry, dict[str, object]]:
    """Read a source shape and its original attribute/ring evidence."""
    source_shape = reader.shape(ordinal)
    attributes = reader.record(ordinal)
    if attributes is None:
        raise ValueError(
            f"Deleted/missing DBF record {ordinal}; retained in raw archive"
        )
    return shape(source_shape.__geo_interface__), {
        "source_attributes": attributes.as_dict(),
        "shp_part_starts": list(source_shape.parts),
        "source_shape_type": source_shape.shapeType,
    }

"""Geoboundaries reader."""

from __future__ import annotations

import shutil
import struct
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import shapefile
import shapely
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from .geoboundaries_json import feature_ids
from .geoboundaries_settings import MAX_SHAPE_BYTES


def _extract(archive_path: Path, directory: Path) -> Path:
    """Extract just the unsimplified shapefile, never duplicate every ZIP member."""
    with zipfile.ZipFile(archive_path) as archive:
        shapes = [
            n
            for n in archive.namelist()
            if n.endswith(".shp") and "_simplified" not in n
        ]
        if len(shapes) != 1:
            raise ValueError("Expected exactly one unsimplified shapefile")
        stem = shapes[0][:-4]
        directory.mkdir(parents=True, exist_ok=True)
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            with (
                archive.open(stem + suffix) as source,
                (directory / ("layer" + suffix)).open("wb") as target,
            ):
                shutil.copyfileobj(source, target, length=1024 * 1024)
    projection = (directory / "layer.prj").read_text(encoding="utf-8")
    if (
        "GEOGCS" not in projection
        or "WGS_1984" not in projection
        or "PROJCS" in projection
    ):
        raise ValueError(f"Unexpected CRS: {projection}")
    return directory / "layer.shp"


def _record_sizes(path: Path) -> Iterator[int]:
    with path.open("rb") as stream:
        header = stream.read(100)
        if len(header) != 100 or struct.unpack_from(">i", header)[0] != 9994:
            raise ValueError("Invalid shapefile header")
        if struct.unpack_from(">i", header, 24)[0] * 2 != path.stat().st_size:
            raise ValueError("Shapefile length mismatch")
        while record := stream.read(8):
            if len(record) != 8:
                raise ValueError("Truncated shapefile record header")
            size = struct.unpack_from(">i", record, 4)[0] * 2
            if size < 4:
                raise ValueError("Invalid shapefile record size")
            yield size
            stream.seek(size, 1)
        if stream.tell() != path.stat().st_size:
            raise ValueError("Truncated shapefile record body")


def _features(
    path: Path,
) -> Iterator[tuple[int, dict[str, Any], BaseGeometry | None, str | None]]:
    """Read one bounded shape; reject before allocating an oversized record."""
    with shapefile.Reader(str(path), encoding="utf-8") as reader:
        fields = [str(field[0]) for field in reader.fields[1:]]
        count = 0
        for index, size in enumerate(_record_sizes(path)):
            count += 1
            record = reader.record(index)
            properties = (
                dict(zip(fields, record, strict=True)) if record is not None else {}
            )
            if size > MAX_SHAPE_BYTES:
                yield (
                    index,
                    properties,
                    None,
                    f"Shape record exceeds {MAX_SHAPE_BYTES} bytes",
                )
                continue
            try:
                source_shape = reader.shape(index)
                if source_shape.shapeType not in (5, 15, 25):
                    raise ValueError(f"Non-polygon shape type {source_shape.shapeType}")
                geometry = shape(source_shape.__geo_interface__)
                if source_shape.shapeType != 5:
                    properties["normalization_dropped_z_or_m"] = True
                del source_shape
                yield index, properties, geometry, None
                del geometry
            except (ValueError, TypeError, shapely.errors.GEOSException) as error:
                yield index, properties, None, f"{type(error).__name__}: {error}"
        if count != reader.numRecords:
            raise ValueError(f"SHP/DBF record mismatch: {count}/{reader.numRecords}")


def _corroborate_count(
    archive_path: Path, identifiers: set[str], published: int
) -> dict[str, object]:
    """Keep source metadata discrepancies when both distributed formats agree."""
    with zipfile.ZipFile(archive_path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.endswith(".geojson") and "_simplified" not in name
        ]
        if len(names) != 1:
            raise ValueError(
                "Publisher feature count mismatch requires "
                "a bounded independent GeoJSON check"
            )
        with archive.open(names[0]) as stream:
            ids = feature_ids(stream)
        if len(ids) != len(identifiers) or set(ids) != identifiers:
            raise ValueError(
                "Publisher feature count mismatch: SHP and GeoJSON disagree"
            )
        return {
            "published_count": published,
            "actual_count": len(ids),
            "geojson_count": len(ids),
            "geojson_member": names[0],
            "geometry_ids_match": True,
            "explanation": (
                "Publisher metadata disagrees with both distributed SHP "
                "and GeoJSON; every available record retained"
            ),
        }

"""Normalize pinned Natural Earth geometry and retain a transformation audit."""

import io
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import shapefile
import shapely
from shapely.geometry import Polygon, box, shape
from shapely.geometry.base import BaseGeometry

from .records import AdminRecord

BBox = tuple[float, float, float, float]
Audit = list[dict[str, Any]]


def features(path: Path) -> Iterator[tuple[dict[str, Any], BaseGeometry]]:
    with zipfile.ZipFile(path) as archive:

        def member(suffix: str) -> io.BytesIO:
            names = [n for n in archive.namelist() if n.endswith(suffix)]
            if len(names) != 1:
                raise ValueError(f"Expected one {suffix} member in {path.name}")
            return io.BytesIO(archive.read(names[0]))

        with shapefile.Reader(
            shp=member(".shp"), shx=member(".shx"), dbf=member(".dbf"), encoding="utf-8"
        ) as reader:
            for row in reader.iterShapeRecords():
                yield row.record.as_dict(), shape(row.shape.__geo_interface__)


def polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [p for g in geometry.geoms for p in polygon_parts(g)]
    return []


def normalize(
    geometry: BaseGeometry, identity: str, audit: Audit, bounds: BBox | None
) -> list[Polygon]:
    if not geometry.is_valid:
        audit.append(
            {
                "operation": "make_valid",
                "id": identity,
                "reason": shapely.is_valid_reason(geometry),
            }
        )
        geometry = shapely.make_valid(geometry)
    clip = box(*(bounds or (-180, -90, 180, 90)))
    geometry = geometry.intersection(clip)
    parts = polygon_parts(geometry)
    for part in parts:
        for ring in (part.exterior, *part.interiors):
            coordinates = np.array(ring.coords)
            jumps = np.abs(np.diff(coordinates[:, 0])) > 180
            polar = (np.abs(coordinates[:-1, 1]) == 90) & (
                np.abs(coordinates[1:, 1]) == 90
            )
            if np.any(jumps & ~polar):
                raise ValueError(f"Unsplit antimeridian ring in {identity}")
    return parts


def iso_code(value: str, *, subdivision: bool = False) -> str:
    pattern = r"[A-Z]{2}-[A-Z0-9]{1,3}" if subdivision else r"[A-Z]{2}"
    return value if re.fullmatch(pattern, value) and not value.startswith("XK") else ""


def administration(
    paths: dict[str, Path], bounds: BBox | None, audit: Audit
) -> tuple[list[AdminRecord], list[AdminRecord]]:
    countries: list[AdminRecord] = []
    for row, geometry in features(paths["countries"]):
        identity = f"ne:country:{row['NE_ID']}"
        countries.append(
            AdminRecord(
                identity,
                row["ADMIN"],
                iso_code(row["ISO_A2_EH"]),
                -1,
                1 if row["ADM0_A3"] in {"ATA", "VAT"} else 0,
                normalize(geometry, identity, audit, bounds),
                row["ADM0_A3"],
            )
        )
    countries.sort(key=lambda c: c.id)
    parents = {c.source_key: i for i, c in enumerate(countries)}
    subdivisions: list[AdminRecord] = []
    for row, geometry in features(paths["admin1"]):
        identity = f"ne:admin1:{row['adm1_code']}"
        if "+00?" in row["adm1_code"] or not row["name"]:
            audit.append({"operation": "remove_placeholder", "id": identity})
            continue
        parent = parents.get(row["adm0_a3"], -1)
        if parent >= 0:
            countries[parent].subdivisions = 2
        parts = normalize(geometry, identity, audit, bounds)
        if not parts:
            continue
        subdivisions.append(
            AdminRecord(
                identity,
                row["name"],
                iso_code(row["iso_3166_2"], subdivision=True),
                parent,
                0,
                parts,
            )
        )
    subdivisions.sort(key=lambda c: c.id)
    validate_parents(countries, subdivisions, audit)
    return countries, subdivisions


def validate_parents(
    countries: list[AdminRecord], children: list[AdminRecord], audit: Audit
) -> None:
    geometries = [shapely.union_all(country.parts) for country in countries]
    for child in children:
        if child.parent < 0:
            audit.append({"operation": "missing_parent", "id": child.id})
            continue
        geometry = shapely.union_all(child.parts)
        outside = geometry.difference(geometries[child.parent]).area
        if outside > 1e-12:
            audit.append(
                {
                    "operation": "parent_geometry_mismatch",
                    "id": child.id,
                    "outside_fraction": outside / geometry.area,
                }
            )

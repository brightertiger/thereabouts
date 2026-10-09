"""Overture areas."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from typing import Any, cast

import shapely
from shapely.geometry.base import BaseMultipartGeometry

from pipeline.sources.shared.geometry import (
    bounds_columns,
    polygon_parts,
    repair_geometry,
)
from pipeline.sources.shared.geometry import split_geometry as bounded_geometry
from pipeline.sources.shared.rows import RowRejected, clean_text

from .rows import _common, _labels, _provenance, encode


def areas(
    row: dict[str, Any],
    context: dict[str, Any],
    parent: str | None,
    stats: Counter[str],
    geometry_bytes: int,
    max_depth: int,
) -> Iterator[dict[str, Any]]:
    geometry = shapely.from_wkb(row["geometry"])
    provenance = _provenance(row, context)
    if geometry.is_empty:
        stats["empty_input"] += 1
        raise RowRejected("empty area geometry")
    invalid = not geometry.is_valid
    if invalid:
        stats["invalid_input"] += 1
        provenance["repair_reason"] = shapely.is_valid_reason(geometry)
    else:
        stats["valid_input"] += 1
    try:
        geometry, changes = repair_geometry(
            geometry, collection="retain", check_extent=False
        )
    except ValueError as error:
        raise RowRejected(str(error)) from error
    if "make_valid" in changes:
        provenance["transformations"].append("GEOS make_valid")
        stats["repaired_input"] += 1
    if shapely.get_coordinate_dimension(geometry) != 2:
        geometry, changes = repair_geometry(
            geometry, collection="retain", force_2d=True, check_extent=False
        )
        provenance["transformations"].extend(changes)
        stats["forced_2d"] += 1
    name, english = _labels(row)
    oversized = len(geometry.wkb) > geometry_bytes
    if geometry.geom_type == "GeometryCollection":
        non_polygon = sum(
            part.geom_type not in ("Polygon", "MultiPolygon", "GeometryCollection")
            for part in cast(BaseMultipartGeometry, geometry).geoms
        )
        stats["repair_non_polygon_components"] += non_polygon
        provenance["repair_non_polygon_components"] = non_polygon
    emitted = 0
    for polygon in polygon_parts(geometry):
        for part in bounded_geometry(polygon, geometry_bytes, max_depth=max_depth):
            part_provenance = {**provenance, "geometry_part": emitted}
            if oversized:
                part_provenance["geometry_split"] = (
                    "components then recursive bbox intersection; no simplification"
                )
            result = {
                **_common(row, context),
                "entity_id": row["division_id"],
                "kind": row["subtype"],
                "subtype": row["subtype"],
                "admin_level": clean_text(row.get("admin_level")),
                "parent_source_id": parent,
                "country_code": clean_text(row.get("country")),
                "subdivision_code": clean_text(row.get("region")),
                "name": name,
                "name_en": english,
                "geometry": part.wkb,
                **bounds_columns(part),
                "is_land": row.get("is_land"),
                "is_territorial": row.get("is_territorial"),
                "provenance": encode(part_provenance),
            }
            emitted += 1
            yield result
    if not emitted:
        raise RowRejected("area has no polygonal components after repair")
    stats["output_valid_geometries"] += emitted
    stats["additional_split_parts"] += emitted - 1

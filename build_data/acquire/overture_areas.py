"""Overture areas."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from typing import Any, cast

import shapely
from shapely.geometry.base import BaseMultipartGeometry

from .geometry import bounds_columns, polygon_parts, repair_geometry
from .geometry import split_geometry as bounded_geometry
from .overture_rows import RowRejectedError, _common, _labels, _provenance, encode, text
from .overture_settings import GEOMETRY_BYTES, SPOTS


def areas(
    row: dict[str, Any],
    context: dict[str, Any],
    parent: str | None,
    stats: Counter[str],
    spots: dict[str, list[dict[str, Any]]],
) -> Iterator[dict[str, Any]]:
    geometry = shapely.from_wkb(row["geometry"])
    provenance = _provenance(row, context)
    if geometry.is_empty:
        stats["empty_input"] += 1
        raise RowRejectedError("empty area geometry")
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
        raise RowRejectedError(str(error)) from error
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
    oversized = len(geometry.wkb) > GEOMETRY_BYTES
    if geometry.geom_type == "GeometryCollection":
        non_polygon = sum(
            part.geom_type not in ("Polygon", "MultiPolygon", "GeometryCollection")
            for part in cast(BaseMultipartGeometry, geometry).geoms
        )
        stats["repair_non_polygon_components"] += non_polygon
        provenance["repair_non_polygon_components"] = non_polygon
    emitted = 0
    for polygon in polygon_parts(geometry):
        for part in bounded_geometry(polygon, GEOMETRY_BYTES, max_depth=24):
            xmin, ymin, xmax, ymax = part.bounds
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
                "admin_level": text(row.get("admin_level")),
                "parent_source_id": parent,
                "country_code": text(row.get("country")),
                "subdivision_code": text(row.get("region")),
                "name": name,
                "name_en": english,
                "geometry": part.wkb,
                **bounds_columns(part),
                "is_land": row.get("is_land"),
                "is_territorial": row.get("is_territorial"),
                "provenance": encode(part_provenance),
            }
            for label, (x, y) in SPOTS.items():
                if (
                    xmin <= x <= xmax
                    and ymin <= y <= ymax
                    and part.covers(shapely.Point(x, y))
                ):
                    spots[label].append(
                        {
                            key: result[key]
                            for key in (
                                "source_id",
                                "entity_id",
                                "name",
                                "name_en",
                                "subtype",
                                "admin_level",
                                "country_code",
                                "is_land",
                                "is_territorial",
                            )
                        }
                    )
            emitted += 1
            yield result
    if not emitted:
        raise RowRejectedError("area has no polygonal components after repair")
    stats["output_valid_geometries"] += emitted
    stats["additional_split_parts"] += emitted - 1

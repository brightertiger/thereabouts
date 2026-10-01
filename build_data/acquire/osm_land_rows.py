"""Osm land rows."""

from __future__ import annotations

import json
from typing import Any

import pyarrow as pa
import shapely
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from .geometry import bounds_columns, repair_geometry
from .osm_land import LICENSE_URL, RELEASE, SOURCE, SOURCE_URL
from .osm_land_settings import SPOT_CHECKS


def _row(
    geometry: BaseGeometry,
    details: dict[str, object],
    ordinal: int,
    inventory: dict[str, Any],
    input_hash: str,
) -> tuple[dict[str, object], dict[str, object] | None]:
    reason = str(shapely.is_valid_reason(geometry)) if not geometry.is_valid else None
    geometry, changes = repair_geometry(geometry)
    audit: dict[str, object] | None = (
        {
            "record_index": ordinal,
            "invalid_reason": reason,
            "repair": "shapely.make_valid",
        }
        if "make_valid" in changes
        else None
    )
    source_id = f"shp-record:{ordinal}"
    provenance = {
        "source_url": SOURCE_URL,
        "license_url": LICENSE_URL,
        "attribution": inventory["attribution"],
        "retrieved_at": inventory["retrieved_at"],
        "input_sha256": input_hash,
        "shp_record_index": ordinal,
        **details,
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
    return {
        "source": SOURCE,
        "source_id": source_id,
        "entity_id": source_id,
        "kind": "land",
        "subtype": "split_land_polygon",
        "geometry": geometry.wkb,
        **bounds_columns(geometry),
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

"""Osm land rows."""

from __future__ import annotations

from typing import Any

import shapely
from shapely.geometry.base import BaseGeometry

from pipeline.sources.contract import SourceContext
from pipeline.sources.shared.geometry import bounds_columns, repair_geometry
from pipeline.sources.shared.rows import canonical_json, provenance


def _row(
    ctx: SourceContext,
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
    evidence = provenance(
        ctx.pin.files[0].url,
        ctx.settings.licence.url,
        inventory["attribution"],
        {
            "retrieved_at": inventory["retrieved_at"],
            "input_sha256": input_hash,
            "shp_record_index": ordinal,
        },
        details,
        {
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
        },
    )
    return {
        "source": ctx.settings.name,
        "source_id": source_id,
        "entity_id": source_id,
        "kind": "land",
        "subtype": "split_land_polygon",
        "geometry": geometry.wkb,
        **bounds_columns(geometry),
        "is_land": True,
        "is_territorial": False,
        "source_release": ctx.pin.release,
        "license": ctx.settings.licence.id,
        "provenance": canonical_json(evidence, separators=None, ensure_ascii=True),
    }, audit

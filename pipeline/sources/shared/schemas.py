"""Version 1 source-neutral Arrow contracts, before entity reconciliation."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, cast

import pyarrow as pa
import shapely

from pipeline.config.schema import H3
from pipeline.config.sources import SourceLimits

from .geometry import BBOX_COLUMNS, BOUND_TOLERANCE, check_bounds, validate_polygon
from .lookup_schemas import LOOKUP_SCHEMAS, LookupKind
from .lookup_validation import validate_lookup_batch

Kind = Literal["areas", "places", "names"] | LookupKind
SCHEMA_VERSION = "1"

_IDENTITY: list[pa.Field[pa.DataType]] = [
    pa.field("source", pa.string(), False),
    pa.field("source_id", pa.string(), False),
]
_PROVENANCE: list[pa.Field[pa.DataType]] = [
    pa.field("source_release", pa.string(), False),
    pa.field("license", pa.string(), False),
    pa.field("provenance", pa.string(), False),
]
_METADATA: dict[bytes | str, bytes | str] = {"acquire_schema_version": SCHEMA_VERSION}

AREAS = pa.schema(
    [
        *_IDENTITY,
        pa.field("entity_id", pa.string(), False),
        pa.field("kind", pa.string(), False),
        pa.field("subtype", pa.string()),
        pa.field("admin_level", pa.string()),
        pa.field("parent_source_id", pa.string()),
        pa.field("country_code", pa.string()),
        pa.field("subdivision_code", pa.string()),
        pa.field("name", pa.string()),
        pa.field("name_en", pa.string()),
        pa.field("geometry", pa.binary(), False),
        pa.field("xmin", pa.float64(), False),
        pa.field("ymin", pa.float64(), False),
        pa.field("xmax", pa.float64(), False),
        pa.field("ymax", pa.float64(), False),
        pa.field("is_land", pa.bool_()),
        pa.field("is_territorial", pa.bool_()),
        *_PROVENANCE,
    ],
    metadata={**_METADATA, "geometry_crs": "EPSG:4326", "geometry_encoding": "WKB"},
)

PLACES = pa.schema(
    [
        *_IDENTITY,
        pa.field("kind", pa.string(), False),
        pa.field("name", pa.string(), False),
        pa.field("name_en", pa.string()),
        pa.field("latitude", pa.float64(), False),
        pa.field("longitude", pa.float64(), False),
        pa.field("feature_class", pa.string()),
        pa.field("feature_code", pa.string()),
        pa.field("subtype", pa.string()),
        pa.field("country_code", pa.string()),
        pa.field("admin1_code", pa.string()),
        pa.field("admin2_code", pa.string()),
        pa.field("parent_source_id", pa.string()),
        pa.field("population", pa.int64()),
        *_PROVENANCE,
    ],
    metadata=_METADATA,
)

NAMES = pa.schema(
    [
        *_IDENTITY,
        pa.field("entity_source_id", pa.string(), False),
        pa.field("name", pa.string(), False),
        pa.field("language", pa.string()),
        pa.field("name_kind", pa.string()),
        pa.field("is_preferred", pa.bool_(), False),
        pa.field("is_short", pa.bool_(), False),
        pa.field("is_colloquial", pa.bool_(), False),
        pa.field("is_historic", pa.bool_(), False),
        pa.field("valid_from", pa.string()),
        pa.field("valid_to", pa.string()),
        *_PROVENANCE,
    ],
    metadata=_METADATA,
)

SCHEMAS: dict[Kind, pa.Schema] = {
    "areas": AREAS,
    "places": PLACES,
    "names": NAMES,
}
for lookup_kind, lookup_schema in LOOKUP_SCHEMAS.items():
    SCHEMAS[lookup_kind] = lookup_schema


def schema_for(kind: Kind, grid: H3) -> pa.Schema:
    """Keep field contracts fixed and label written lookup files with their grid."""
    schema = SCHEMAS[kind]
    if b"h3_reference_resolution" in (schema.metadata or {}):
        return schema.with_metadata(
            {
                **(schema.metadata or {}),
                b"h3_reference_resolution": str(grid.cell_resolution).encode(),
            }
        )
    return schema


SCHEMA_HASHES: dict[Kind, str] = {
    kind: hashlib.sha256(schema.serialize().to_pybytes()).hexdigest()
    for kind, schema in SCHEMAS.items()
}


# These source families publish only areas, places and names. Independent
# lookup/plate contracts must not invalidate their existing checkpoints.
CORE_SCHEMA_HASHES = {
    kind: digest
    for kind, digest in SCHEMA_HASHES.items()
    if kind in ("areas", "places", "names")
}


def _provenance(row: dict[str, object]) -> None:
    value = json.loads(cast(str, row["provenance"]))
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), str) or not value[key].strip()
        for key in ("source_url", "license_url", "attribution")
    ):
        raise ValueError(
            "provenance needs source_url, license_url and attribution strings"
        )


def _area(row: dict[str, object]) -> None:
    bounds = tuple(cast(float, row[c]) for c in BBOX_COLUMNS)
    check_bounds(bounds)
    try:
        geometry = shapely.from_wkb(cast(bytes, row["geometry"]))
    except shapely.errors.GEOSException as error:
        raise ValueError("Invalid WKB") from error
    validate_polygon(geometry)
    if any(
        abs(a - b) > BOUND_TOLERANCE
        for a, b in zip(bounds, geometry.bounds, strict=True)
    ):
        raise ValueError("Bounding box does not match geometry")


def validate_table(
    table: pa.Table | pa.RecordBatch,
    kind: Kind,
    source: str,
    limits: SourceLimits,
    *,
    grid: H3,
) -> None:
    """Validate schema, nulls, byte bounds, coordinates, WKB and provenance."""
    schema = SCHEMAS[kind]
    if not table.schema.equals(schema, check_metadata=False):
        raise ValueError(f"Expected the exact {kind} schema (including nullability)")
    if table.nbytes > limits.row_group_bytes:
        raise ValueError("Batch exceeds 32 MB; split it before validation/writing")
    for field in schema:
        if not field.nullable and table.column(field.name).null_count:
            raise ValueError(f"Required column contains null: {field.name}")
    batches = (
        table.to_batches(max_chunksize=1024) if isinstance(table, pa.Table) else [table]
    )
    for batch in batches:
        if kind in LOOKUP_SCHEMAS:
            validate_lookup_batch(
                batch, kind, (source,), _provenance, limits.row_bytes, grid=grid
            )
            continue
        for index, row in enumerate(batch.to_pylist()):
            if batch.slice(index, 1).nbytes > limits.row_bytes:
                raise ValueError(
                    "Row exceeds 8 MB; split geometry or isolate oversized input"
                )
            for field in schema:
                if (
                    pa.types.is_string(field.type)
                    and row[field.name] is not None
                    and not row[field.name].strip()
                ):
                    raise ValueError(f"Use null for missing strings: {field.name}")
            if row["source"] != source:
                raise ValueError("Unknown source")
            _provenance(row)
            country = row.get("country_code")
            if country is not None and (
                len(country) != 2
                or not country.isascii()
                or not country.isalpha()
                or country != country.upper()
            ):
                raise ValueError("country_code must be uppercase ISO alpha-2 (or XK)")
            if kind == "areas":
                _area(row)
            elif kind == "places":
                if not (
                    -90 <= row["latitude"] <= 90 and -180 <= row["longitude"] <= 180
                ):
                    raise ValueError("Invalid point coordinates")
                if row["population"] is not None and row["population"] < 0:
                    raise ValueError("Population cannot be negative")

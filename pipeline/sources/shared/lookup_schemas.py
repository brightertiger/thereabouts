"""Additive lookup contracts; the original three schemas remain byte-identical."""

from __future__ import annotations

import ipaddress
import math
from typing import Any, Literal

import h3
import pyarrow as pa
import shapely

from pipeline.config.schema import H3

from .geometry import validate_polygon
from .plates_schemas import PLATE_KINDS, PLATE_SCHEMAS, PlateKind
from .plates_validation import validate_plate

LookupKind = (
    Literal[
        "postal_codes",
        "countries",
        "subdivisions",
        "airports",
        "trade_locations",
        "timezones",
        "timezone_cells",
        "zone_tables",
        "phone_metadata",
        "phone_prefixes",
        "ip_ranges",
    ]
    | PlateKind
)
CORE_LOOKUP_KINDS: tuple[LookupKind, ...] = (
    "postal_codes",
    "countries",
    "subdivisions",
    "airports",
    "trade_locations",
    "timezones",
    "timezone_cells",
    "zone_tables",
    "phone_metadata",
    "phone_prefixes",
    "ip_ranges",
)
KINDS = (*CORE_LOOKUP_KINDS, *PLATE_KINDS)


def fields(names: str) -> list[pa.Field[pa.DataType]]:
    return [pa.field(name, pa.string()) for name in names.split()]


IDENTITY: list[pa.Field[pa.DataType]] = [
    pa.field("source", pa.string(), False),
    pa.field("source_id", pa.string(), False),
]
PROVENANCE: list[pa.Field[pa.DataType]] = [
    pa.field(name, pa.string(), False)
    for name in ("source_release", "license", "provenance")
]
POINT: list[pa.Field[pa.DataType]] = [
    pa.field("latitude", pa.float64()),
    pa.field("longitude", pa.float64()),
    pa.field("h3", pa.string()),
    pa.field("h3_uint64", pa.uint64()),
    pa.field("h3_resolution", pa.uint8()),
]
CELL: list[pa.Field[pa.DataType]] = [
    pa.field("h3", pa.string(), False),
    pa.field("h3_uint64", pa.uint64(), False),
    pa.field("h3_resolution", pa.uint8(), False),
]


def schema(columns: list[pa.Field[pa.DataType]]) -> pa.Schema:
    return pa.schema(
        [*IDENTITY, *columns, *PROVENANCE],
        metadata={
            "acquire_schema_version": "1",
            "lookup_schema_version": "1",
            "h3_reference_resolution": str(H3().cell_resolution),
        },
    )


LOOKUP_SCHEMAS: dict[LookupKind, pa.Schema] = {
    "postal_codes": schema(
        [
            *fields(
                "country_code postal_code place_name admin1_name admin1_code "
                "admin2_name admin2_code admin3_name admin3_code accuracy "
                "variant"
            ),
            *POINT,
        ]
    ),
    "countries": schema(
        fields(
            "country_code alpha3 numeric name calling_code currency languages "
            "tld continent m49 region_code region_name subregion_code "
            "subregion_name intermediate_region_code intermediate_region_name"
        )
    ),
    "subdivisions": schema(
        fields(
            "code code_system country_code name type parent_code geoname_id name_ascii"
        )
    ),
    "airports": schema(
        [
            *fields(
                "ident iata_code icao_code gps_code local_code type name "
                "municipality country_code region_code"
            ),
            *POINT,
        ]
    ),
    "trade_locations": schema(
        [
            *fields(
                "locode country_code location name name_ascii subdivision_code "
                "function status iata_code date change remarks coordinates_raw"
            ),
            *POINT,
        ]
    ),
    "timezones": schema(
        [
            pa.field("tzid", pa.string(), False),
            pa.field("part", pa.uint32(), False),
            pa.field("geometry", pa.binary(), False),
            pa.field("is_ocean", pa.bool_(), False),
        ]
    ),
    "timezone_cells": schema([pa.field("tzid", pa.string(), False), *CELL]),
    "zone_tables": schema(
        [*fields("table tzid country_codes comments coordinates_raw"), *POINT]
    ),
    "phone_metadata": schema(
        fields(
            "territory calling_code leading_digits national_prefix "
            "international_prefix metadata_xml"
        )
    ),
    "phone_prefixes": schema(
        [
            *fields("prefix calling_code language description"),
            pa.field("country_codes", pa.list_(pa.string()), False),
        ]
    ),
    "ip_ranges": schema(
        [
            *fields("ip_start ip_end country_code region city"),
            pa.field("ip_version", pa.uint8(), False),
            pa.field("ip_start_packed", pa.binary(16), False),
            pa.field("ip_end_packed", pa.binary(16), False),
            *POINT,
        ]
    ),
}
for plate_kind, plate_schema in PLATE_SCHEMAS.items():
    LOOKUP_SCHEMAS[plate_kind] = plate_schema


def validate_lookup(row: dict[str, Any], kind: str, *, grid: H3) -> None:
    """Check stored cells, point agreement, IP ordering and bounded area geometry."""
    if kind in PLATE_KINDS:
        validate_plate(row, kind)
    if "h3" in row:
        cell, number, resolution = row["h3"], row["h3_uint64"], row["h3_resolution"]
        if cell is None:
            if any(
                row.get(key) is not None
                for key in ("h3_uint64", "h3_resolution", "latitude", "longitude")
            ):
                raise ValueError("Missing H3 key for located record")
        elif (
            not h3.is_valid_cell(cell)
            or h3.int_to_str(number) != cell
            or h3.get_resolution(cell) != resolution
            or not 0 <= resolution <= grid.cell_resolution
        ):
            raise ValueError("Invalid canonical H3 key or resolution")
        if row.get("latitude") is not None:
            lat, lon = row["latitude"], row["longitude"]
            if not (
                math.isfinite(lat)
                and math.isfinite(lon)
                and -90 <= lat <= 90
                and -180 <= lon <= 180
            ):
                raise ValueError("Invalid coordinates")
            if (
                resolution != grid.cell_resolution
                or h3.latlng_to_cell(lat, lon, grid.cell_resolution) != cell
            ):
                raise ValueError(
                    f"Point does not match resolution-{grid.cell_resolution} cell"
                )
    if kind == "ip_ranges":
        start, end = (
            ipaddress.ip_address(row["ip_start"]),
            ipaddress.ip_address(row["ip_end"]),
        )
        if (
            start.version != end.version
            or start.version != row["ip_version"]
            or int(start) > int(end)
        ):
            raise ValueError("Invalid IP range")
        if (
            start.packed.rjust(16, b"\0") != row["ip_start_packed"]
            or end.packed.rjust(16, b"\0") != row["ip_end_packed"]
        ):
            raise ValueError("IP packed key mismatch")
    if kind == "timezones":
        validate_polygon(shapely.from_wkb(row["geometry"]))

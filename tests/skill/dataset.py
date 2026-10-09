"""A tiny release-shaped dataset for the skill examples.

Its places, cells and codes are coherent with the committed sample packs, so a
pack answer can be followed into the tables. The layout mirrors a release:
``<table>/part.parquet``, ``places/country=XX/``, ``cells/group=<r1 hex>/``, and a
``manifest.json`` listing every table file by kind. Every table of
config/dataset.yaml is written, empty when no row is given here.
"""

import hashlib
import ipaddress
import json
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq
from h3.api import basic_int as h3

from pipeline.release.dataset_schema import load
from pipeline.runtime.fingerprints import REPOSITORY

Row = dict[str, Any]

FRANCE = "state:overture:b2ff5988-9aa6-4fae-9b01-1c2700d2f567"
FLANDERS = "state:overture:5f5c9898-672a-4afc-aa46-a27d3ebce45c"
WALLONIA = "state:overture:35a36044-ac48-4742-8ee0-e97e63af28eb"
BRUSSELS_REGION = "state:overture:5cbce05b-ffe3-41cf-afdd-b41d3b9352c7"
CALIFORNIA = "state:overture:4c555166-326b-48b4-8a33-155eb7c23e8d"
PARIS, TREMBLAY = "city:geonames:2988507", "city:geonames:2971874"
ANTWERP, BRUSSELS = "city:geonames:2803138", "city:geonames:2800866"
MOUNTAIN_VIEW, MONT = "city:geonames:5375480", "city:geonames:2790838"
FLATWILLOW = "city:geonames:5652421"
ARRONDISSEMENT = "city:fixture:paris-1er"

DEFAULTS: dict[str, Any] = {
    "string": "fixture",
    "double": 0.0,
    "int64": 0,
    "uint64": 0,
    "uint8": 0,
    "bool": False,
    "binary": b"",
    "list<element: string>": [],
}


def place(identifier: str, role: str, name: str, country: str, **more: Any) -> Row:
    city = role in {"city", "town"}
    kind = more.pop("settlement_kind", role)
    row: Row = {
        "place_id": identifier,
        "role": role,
        "name": name,
        "name_en": name,
        "country_code": country,
        "code_status": "source",
        "settlement_kind": kind,
        "normalized_city_id": identifier if city else None,
        "normalization_method": "self" if city else "non_settlement",
        "parent_id": None if role == "country" else f"country:{country}",
    }
    return row | more


def canonical(identifier: str, name: str, country: str, **more: Any) -> Row:
    return {
        "city_id": identifier,
        "place_id": identifier,
        "country_code": country,
        "name": name,
        "name_en": name,
        "kind": more.pop("kind", "city"),
        "eligibility": "population and active settlement",
        "allocation_rule": "bounded",
        "source_ids": "[]",
        "footprint_references": "[]",
    } | more


def cell(
    index: str, country: str, state: str | None, city: str | None, **more: Any
) -> Row:
    value = int(index, 16)
    return {
        "h3": index,
        "h3_uint64": value,
        "h3_resolution": h3.get_resolution(value),
        "country_id": f"country:{country}",
        "state_id": state,
        "city_id": city,
        "country_method": "area",
        "state_method": "area" if state else None,
        "city_method": more.pop("method", "city_polygon") if city else None,
        "land_method": "land",
    } | more


def located(index: str, country: str, state: str | None, city: str | None) -> Row:
    value = int(index, 16)
    point = h3.cell_to_latlng(value)
    return {
        "latitude": point[0],
        "longitude": point[1],
        "h3": index,
        "h3_uint64": value,
        "h3_resolution": h3.get_resolution(value),
        "country_id": f"country:{country}",
        "state_id": state,
        "city_id": city,
        "cell_country_code": country,
        "cell_status": "matched",
        "country_disagrees": False,
    }


def cell_at(lat: float, lon: float) -> str:
    return f"{h3.latlng_to_cell(lat, lon, 8):x}"


def packed(address: str) -> bytes:
    return ipaddress.ip_address(address).packed.rjust(16, b"\0")


def interval(start: str, end: str, city: str, region: str, state: str) -> Row:
    version = ipaddress.ip_address(start).version
    row = located("8828347509fffff", "US", state, MOUNTAIN_VIEW)
    return row | {
        "ip_start": start,
        "ip_end": end,
        "ip_version": version,
        "ip_start_packed": packed(start),
        "ip_end_packed": packed(end),
        "country_code": "US",
        "region": region,
        "city": city,
    }


def code_links(country: str | None, status: str = "matched") -> Row:
    return {
        "country_id": f"country:{country}" if country else None,
        "place_id": f"country:{country}" if country and status == "matched" else None,
        "place_ids": [f"country:{country}"] if country else [],
        "link_status": status,
        "link_method": "source country code",
    }


ROWS: dict[str, list[Row]] = {
    "places": [
        place("country:FR", "country", "France", "FR"),
        place("country:BE", "country", "Belgium", "BE"),
        place("country:US", "country", "United States", "US"),
        place("country:IN", "country", "India", "IN"),
        place(FRANCE, "state", "Île-de-France", "FR", parent_method=None),
        place(FLANDERS, "state", "Flanders", "BE"),
        place(WALLONIA, "state", "Wallonia", "BE"),
        place(BRUSSELS_REGION, "state", "Brussels-Capital Region", "BE"),
        place(CALIFORNIA, "state", "California", "US"),
        place(PARIS, "city", "Paris", "FR", population=2138551, parent_id=FRANCE),
        place(TREMBLAY, "town", "Tremblay-en-France", "FR", population=35591),
        place(ANTWERP, "city", "Antwerp", "BE", population=529247, parent_id=FLANDERS),
        place(BRUSSELS, "city", "Brussels", "BE", population=1019022),
        place(MOUNTAIN_VIEW, "city", "Mountain View", "US", population=80435),
        place(
            ARRONDISSEMENT,
            "settlement",
            "Paris 1er Arrondissement",
            "FR",
            settlement_kind="city_part",
            normalized_city_id=PARIS,
            normalization_method="spatial_absorption",
        ),
        place(MONT, "settlement", "Mont à Leux", "BE", settlement_kind="settlement")
        | {"normalized_city_id": MONT, "normalization_method": "self"},
        place(FLATWILLOW, "settlement", "Flatwillow Colony", "US")
        | {"settlement_kind": "settlement", "normalized_city_id": FLATWILLOW}
        | {"normalization_method": "self"},
    ],
    "canonical_cities": [
        canonical(PARIS, "Paris", "FR", latitude=48.85341, longitude=2.3488)
        | {"population": 2138551},
        canonical(TREMBLAY, "Tremblay-en-France", "FR", kind="town")
        | {"latitude": 48.94956, "longitude": 2.5684, "population": 35591},
        canonical(ANTWERP, "Antwerp", "BE", latitude=51.22047, longitude=4.40026)
        | {"population": 529247},
        canonical(BRUSSELS, "Brussels", "BE", latitude=50.85045, longitude=4.34878)
        | {"population": 1019022},
        canonical(MOUNTAIN_VIEW, "Mountain View", "US", latitude=37.38605)
        | {"longitude": -122.08385, "population": 80435},
    ],
    "cells": [
        cell("871fb4662ffffff", "FR", FRANCE, PARIS),
        cell("881fb42a99fffff", "FR", FRANCE, TREMBLAY, method="urban_allocation"),
        cell("861fa4c5fffffff", "BE", FLANDERS, ANTWERP),
        cell("88194d2a41fffff", "BE", WALLONIA, MONT, method="rural_nearest"),
        cell("872791210ffffff", "US", None, FLATWILLOW, method="rural_nearest_distant"),
        cell("8828347509fffff", "US", CALIFORNIA, MOUNTAIN_VIEW),
        cell("881fb46621fffff", "FR", FRANCE, PARIS),
    ],
    "countries": [
        {
            "country_code": cc,
            "alpha3": alpha3,
            "numeric": number,
            "name": name,
            "calling_code": calling,
            "currency": currency,
            "tld": f".{cc.lower()}",
        }
        | code_links(cc)
        for cc, alpha3, number, name, calling, currency in [
            ("FR", "FRA", "250", "France", "33", "EUR"),
            ("BE", "BEL", "056", "Belgium", "32", "EUR"),
            ("US", "USA", "840", "United States", "1", "USD"),
            ("IN", "IND", "356", "India", "91", "INR"),
        ]
    ],
    "subdivisions": [
        {
            "code": code,
            "code_system": "GeoNames-admin1",
            "country_code": cc,
            "name": name,
        }
        | code_links(cc)
        | {"place_id": place_id}
        for code, cc, name, place_id in [
            ("FR.A8", "FR", "Île-de-France", FRANCE),
            ("BE.VLG", "BE", "Flanders", FLANDERS),
            ("BE.WAL", "BE", "Wallonia", WALLONIA),
            ("US.CA", "US", "California", CALIFORNIA),
        ]
    ],
    "airports": [
        {
            "ident": "LFPG",
            "iata_code": "CDG",
            "icao_code": "LFPG",
            "type": "large_airport",
            "name": "Charles de Gaulle International Airport",
            "municipality": "Paris (Roissy-en-France, Val-d'Oise)",
            "country_code": "FR",
        }
        | located("881fb42a99fffff", "FR", FRANCE, TREMBLAY),
        {
            "ident": "EBBR",
            "iata_code": "BRU",
            "icao_code": "EBBR",
            "type": "large_airport",
            "name": "Brussels Airport",
            "municipality": "Brussels",
            "country_code": "BE",
        }
        | located("881fa4c595fffff", "BE", FLANDERS, None),
        {
            "ident": "KSFO",
            "iata_code": "SFO",
            "icao_code": "KSFO",
            "type": "large_airport",
            "name": "San Francisco International Airport",
            "municipality": "San Francisco",
            "country_code": "US",
        }
        | located("8828347509fffff", "US", CALIFORNIA, None),
    ],
    "postal_codes": [
        {
            "country_code": "FR",
            "postal_code": "75001",
            "place_name": "Paris 01 Louvre",
            "admin1_name": "Île-de-France",
        }
        | located("881fb46625fffff", "FR", FRANCE, PARIS),
        {
            "country_code": "FR",
            "postal_code": "75002",
            "place_name": "Paris 02 Bourse",
            "admin1_name": "Île-de-France",
        }
        | located("881fb46621fffff", "FR", FRANCE, PARIS),
        {"country_code": "IN", "postal_code": "744301", "place_name": "Passa"}
        | located(cell_at(11.67, 92.74), "IN", None, None),
        {"country_code": "IN", "postal_code": "744301", "place_name": "Mus"}
        | located(cell_at(11.66, 92.73), "IN", None, None),
    ],
    "trade_locations": [
        {
            "locode": "BEANR",
            "country_code": "BE",
            "location": "ANR",
            "name": "Antwerpen",
            "name_ascii": "Antwerpen",
            "subdivision_code": "VAN",
            "function": "12345---",
            "status": "AI",
        }
        | located("881fa4c595fffff", "BE", FLANDERS, ANTWERP),
        {
            "locode": "BEBRU",
            "country_code": "BE",
            "location": "BRU",
            "name": "Bruxelles",
            "name_ascii": "Bruxelles",
            "function": "-2-4----",
            "status": "AI",
        }
        | located("881fa4c595fffff", "BE", BRUSSELS_REGION, BRUSSELS),
    ],
    "ip_ranges": [
        interval("8.8.8.0", "8.8.8.255", "Mountain View", "California", CALIFORNIA),
        interval("8.8.4.0", "8.8.4.255", "Mountain View", "California", CALIFORNIA),
        interval(
            "2001:4860::",
            "2001:4860:ffff:ffff:ffff:ffff:ffff:ffff",
            "Mountain View",
            "California",
            CALIFORNIA,
        ),
    ],
    "phone_metadata": [
        {"territory": cc, "calling_code": calling} | code_links(cc)
        for cc, calling in [("FR", "33"), ("BE", "32"), ("US", "1")]
    ],
    "phone_prefixes": [
        {
            "prefix": prefix,
            "calling_code": calling,
            "language": "en",
            "description": description,
            "country_codes": [cc],
        }
        | code_links(cc)
        for prefix, calling, description, cc in [
            ("32", "32", "Belgium", "BE"),
            ("322", "32", "Brussels", "BE"),
            ("3232", "32", "Antwerp", "BE"),
            ("33", "33", "France", "FR"),
            ("331", "33", "Paris", "FR"),
        ]
    ],
    "timezone_cells": [
        {"tzid": "Europe/Paris", "h3": "871fb4662ffffff"},
        {"tzid": "Europe/Brussels", "h3": "861fa4c5fffffff"},
        {"tzid": "America/Los_Angeles", "h3": "8828347509fffff"},
    ],
    "zone_tables": [
        {"table": "zone.tab", "tzid": tzid, "country_codes": cc}
        for tzid, cc in [
            ("Europe/Paris", "FR"),
            ("Europe/Brussels", "BE"),
            ("America/Los_Angeles", "US"),
        ]
    ],
}
ROWS["place_to_city"] = [
    {
        "place_id": row["place_id"],
        "city_id": row["normalized_city_id"],
        "method": row["normalization_method"],
    }
    for row in ROWS["places"]
]
for _row in ROWS["timezone_cells"]:
    _value = int(_row["h3"], 16)
    _row |= {"h3_uint64": _value, "h3_resolution": h3.get_resolution(_value)}


def arrow_type(name: Any) -> pa.DataType:
    if name.startswith("list<"):
        return pa.list_(pa.field("element", pa.string()))
    return cast(pa.DataType, pa.type_for_alias(name))


def partition(table: str, row: Row, countries: dict[str, str]) -> str:
    if table == "cells":
        return f"group={h3.cell_to_parent(row['h3_uint64'], 1):x}"
    if table in {"places", "canonical_cities"}:
        return f"country={row['country_code']}"
    if table == "place_to_city":
        return f"country={countries[row['place_id']]}"
    return ""


def build(root: Path) -> Path:
    """Write the fixture release under `root` and return the directory."""
    schema = load(REPOSITORY / "config/dataset.yaml")
    countries = {r["place_id"]: r["country_code"] for r in ROWS["places"]}
    tables: list[Row] = []
    for name, description in schema.items():
        fields = [
            pa.field(c["name"], arrow_type(c["type"]), nullable=c["nullable"])
            for c in description["columns"]
        ]
        arrow = pa.schema(fields)
        required = {
            c["name"]: c["type"] for c in description["columns"] if not c["nullable"]
        }
        parts: dict[str, list[Row]] = {}
        for row in ROWS.get(name, []):
            filled = {key: DEFAULTS[kind] for key, kind in required.items()} | row
            parts.setdefault(partition(name, filled, countries), []).append(filled)
        for label in parts or {""}:
            path = (
                root / name / label / "part.parquet"
                if label
                else root / name / "part.parquet"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = parts.get(label, [])
            pq.write_table(pa.Table.from_pylist(rows, schema=arrow), path)
            tables.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "kind": name,
                    "rows": len(rows),
                }
            )
    manifest = {
        "completed": True,
        "version": "fixture",
        "tables": tables,
        "files": tables,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return root

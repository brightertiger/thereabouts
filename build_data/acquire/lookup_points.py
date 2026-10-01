"""Postal, airport, trade and IP row conversions, with no eligibility filtering."""

import ipaddress
import re

from .lookup_rows import Reject, Row, point

POSTAL_FIELDS = [
    "country_code",
    "postal_code",
    "place_name",
    "admin1_name",
    "admin1_code",
    "admin2_name",
    "admin2_code",
    "admin3_name",
    "admin3_code",
    "latitude",
    "longitude",
    "accuracy",
]


def postal(raw: list[str], variant: str) -> Row:
    if len(raw) != 12:
        raise Reject(f"Expected 12 postal columns, got {len(raw)}")
    row = dict(zip(POSTAL_FIELDS, raw, strict=True))
    return {**row, **point(row["latitude"], row["longitude"]), "variant": variant}


def airport(raw: dict[str, str]) -> Row:
    mapping = {"country_code": "iso_country", "region_code": "iso_region"}
    names = [
        "ident",
        "iata_code",
        "icao_code",
        "gps_code",
        "local_code",
        "type",
        "name",
        "municipality",
        "country_code",
        "region_code",
    ]
    return {
        **{name: raw.get(mapping.get(name, name)) for name in names},
        **point(raw.get("latitude_deg"), raw.get("longitude_deg")),
    }


def locode_coordinates(value: str) -> Row:
    if not value.strip():
        return point(None, None)
    match = re.fullmatch(r"(\d{2})(\d{2})([NS])\s+(\d{3})(\d{2})([EW])", value.strip())
    if match is None:
        return {
            **point(None, None),
            "coordinate_error": "invalid UN/LOCODE coordinate syntax",
        }
    latd, latm, ns, lond, lonm, ew = match.groups()
    if int(latm) >= 60 or int(lonm) >= 60:
        return {**point(None, None), "coordinate_error": "invalid coordinate minutes"}
    return point(
        (int(latd) + int(latm) / 60) * (-1 if ns == "S" else 1),
        (int(lond) + int(lonm) / 60) * (-1 if ew == "W" else 1),
    )


def trade(raw: dict[str, str]) -> Row:
    names = {
        "country_code": "Country",
        "location": "Location",
        "name": "Name",
        "name_ascii": "NameWoDiacritics",
        "subdivision_code": "Subdivision",
        "function": "Function",
        "status": "Status",
        "iata_code": "IATA",
        "date": "Date",
        "change": "Change",
        "remarks": "Remarks",
        "coordinates_raw": "Coordinates",
    }
    return {
        **{k: raw.get(v) for k, v in names.items()},
        "locode": raw["Country"] + raw["Location"],
        **locode_coordinates(raw.get("Coordinates", "")),
    }


def ip_range(raw: list[str]) -> Row:
    if len(raw) != 8:
        raise Reject(f"Expected 8 DB-IP columns, got {len(raw)}")
    try:
        start, end = ipaddress.ip_address(raw[0]), ipaddress.ip_address(raw[1])
        if start.version != end.version or int(start) > int(end):
            raise ValueError("reversed or mixed-family range")
    except ValueError as error:
        raise Reject(str(error)) from error
    return dict(
        ip_start=str(start),
        ip_end=str(end),
        ip_version=start.version,
        ip_start_packed=start.packed.rjust(16, b"\0"),
        ip_end_packed=end.packed.rjust(16, b"\0"),
        country_code=raw[3],
        region=raw[4],
        city=raw[5],
        **point(raw[6], raw[7]),
    )

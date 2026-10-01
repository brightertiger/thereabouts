"""Country and subdivision codes retain their distinct upstream code systems."""

import csv
from pathlib import Path

from .lookup_rows import Row


def geonames_countries(path: Path) -> dict[str, list[str]]:
    with path.open(encoding="utf-8") as stream:
        return {
            row[0]: row
            for row in csv.reader(
                (line for line in stream if not line.startswith("#")), delimiter="\t"
            )
            if row
        }


def country(raw: dict[str, str], reference: dict[str, list[str]]) -> Row:
    code = raw.get("ISO3166-1-Alpha-2", "")
    gn = reference.get(code, [])

    def fallback(index: int) -> str:
        return gn[index] if len(gn) > index else ""

    mapping = {
        "country_code": "ISO3166-1-Alpha-2",
        "alpha3": "ISO3166-1-Alpha-3",
        "numeric": "ISO3166-1-numeric",
        "name": "CLDR display name",
        "calling_code": "Dial",
        "currency": "ISO4217-currency_alphabetic_code",
        "languages": "Languages",
        "tld": "TLD",
        "continent": "Continent",
        "m49": "M49",
        "region_code": "Region Code",
        "region_name": "Region Name",
        "subregion_code": "Sub-region Code",
        "subregion_name": "Sub-region Name",
        "intermediate_region_code": "Intermediate Region Code",
        "intermediate_region_name": "Intermediate Region Name",
    }
    row = {key: raw.get(value, "") for key, value in mapping.items()}
    for key, index in (
        ("alpha3", 1),
        ("numeric", 2),
        ("name", 4),
        ("calling_code", 12),
        ("currency", 10),
        ("languages", 15),
        ("tld", 9),
        ("continent", 8),
    ):
        if not row[key].strip():
            row[key] = fallback(index)
    for name in (
        "numeric",
        "m49",
        "region_code",
        "subregion_code",
        "intermediate_region_code",
    ):
        if row[name].isdigit():
            row[name] = row[name].zfill(3)
    return row


def subdivision(raw: Row, name: str) -> Row:
    if name == "iso3166-2.json":
        code = raw["code"]
        parent = raw.get("parent")
        return dict(
            code=code,
            code_system="ISO-3166-2",
            country_code=code[:2],
            name=raw["name"],
            type=raw["type"],
            parent_code=(f"{code[:2]}-{parent}" if parent else None),
        )
    values = raw["fields"]
    return dict(
        code=values[0],
        code_system="GeoNames-admin1",
        country_code=values[0][:2],
        name=values[1],
        name_ascii=values[2],
        geoname_id=values[3],
    )

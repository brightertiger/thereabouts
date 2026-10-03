"""Country and subdivision codes retain upstream systems and fallback evidence."""

import csv
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

from pipeline.config.source_options import Text as Options

from .contract import SourceContext
from .shared.lookup_rows import Row
from .shared.text import InputRow, publish_rows


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


def records(ctx: SourceContext, reference: dict[str, list[str]]) -> Iterator[InputRow]:
    for pin in ctx.pin.files:
        name = str(pin.metadata.get("key", pin.name))
        path = ctx.input(pin.name)
        if name == "country-codes.csv":
            pin = replace(
                pin,
                metadata={
                    **pin.metadata,
                    "license": "PDDL-1.0 AND CC-BY-4.0",
                    "attribution": str(
                        pin.metadata.get(
                            "attribution", ctx.settings.licence.attribution
                        )
                    )
                    + "; GeoNames countryInfo (CC-BY-4.0)",
                },
            )
            seen: set[str] = set()
            ordinal = 0
            with path.open(encoding="utf-8-sig", newline="") as stream:
                for ordinal, raw in enumerate(csv.DictReader(stream), 1):
                    code = raw["ISO3166-1-Alpha-2"]
                    seen.add(code)
                    evidence: Row = {**raw, "geonames_countryInfo": reference.get(code)}
                    yield InputRow("countries", pin, ordinal, evidence)
            for code in sorted(reference.keys() - seen):
                ordinal += 1
                yield InputRow(
                    "countries",
                    pin,
                    ordinal,
                    {
                        "ISO3166-1-Alpha-2": code,
                        "geonames_countryInfo": reference[code],
                    },
                )
        elif name == "iso3166-2.json":
            for ordinal, raw in enumerate(json.loads(path.read_bytes())["3166-2"], 1):
                yield InputRow("subdivisions", pin, ordinal, raw)
        elif name == "admin1CodesASCII.txt":
            with path.open(encoding="utf-8") as stream:
                for ordinal, values in enumerate(csv.reader(stream, delimiter="\t"), 1):
                    yield InputRow("subdivisions", pin, ordinal, {"fields": values})


def normalize(ctx: SourceContext) -> list[Path]:
    for name in ("country-codes.csv", "iso3166-2.json", "admin1CodesASCII.txt"):
        ctx.named(name)
    reference = geonames_countries(ctx.input(ctx.named("countryInfo.txt").name))

    def convert(item: InputRow) -> Row:
        if item.kind == "countries":
            return country(item.raw, reference)
        return subdivision(item.raw, str(item.pin.metadata.get("key", item.pin.name)))

    return publish_rows(ctx, records(ctx, reference), convert)


__all__ = ["Options", "normalize"]

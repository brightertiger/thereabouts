"""Streaming text readers; raw archives stay compressed on disk."""

import csv
import gzip
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import cast

from .lookup_codes import geonames_countries
from .lookup_phone import territories
from .lookup_rows import Row
from .lookup_schemas import LookupKind


def records(
    source: str, name: str, pin: Row, inventory: Row
) -> Iterator[tuple[LookupKind, Row]]:
    path = Path(pin["path"])
    if source == "postal" and name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if member.endswith(".txt") and "readme" not in member.lower():
                    with (
                        archive.open(member) as data,
                        io.TextIOWrapper(data, encoding="utf-8-sig") as stream,
                    ):
                        for row in csv.reader(
                            stream, delimiter="\t", quoting=csv.QUOTE_NONE
                        ):
                            yield "postal_codes", {"fields": row, "member": member}
    elif source == "dbip" and name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for row in csv.reader(stream):
                yield "ip_ranges", {"fields": row}
    elif (source, name) in (
        ("airports", "airports.csv"),
        ("unlocode", "code-list.csv"),
        ("codes", "country-codes.csv"),
    ):
        kind = cast(
            LookupKind,
            {
                "airports": "airports",
                "unlocode": "trade_locations",
                "codes": "countries",
            }[source],
        )
        seen: set[str] = set()
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for raw in csv.DictReader(stream):
                if source == "codes":
                    seen.add(raw["ISO3166-1-Alpha-2"])
                yield kind, raw
        if source == "codes":
            reference = geonames_countries(
                Path(inventory["files"]["countryInfo.txt"]["path"])
            )
            for code in sorted(reference.keys() - seen):
                yield kind, {"ISO3166-1-Alpha-2": code}
    elif source == "codes" and name == "iso3166-2.json":
        for raw in json.loads(path.read_text())["3166-2"]:
            yield "subdivisions", raw
    elif source == "codes" and name == "admin1CodesASCII.txt":
        with path.open(encoding="utf-8") as stream:
            for row in csv.reader(stream, delimiter="\t"):
                yield "subdivisions", {"fields": row}
    elif source == "phone" and name.endswith("PhoneNumberMetadata.xml"):
        for raw in territories(path):
            yield "phone_metadata", raw
    elif source == "phone" and name.startswith("resources/geocoding/"):
        with path.open(encoding="utf-8-sig") as stream:
            for line in stream:
                if line.strip() and not line.startswith("#"):
                    yield "phone_prefixes", {"fields": line.rstrip("\n").split("|", 1)}

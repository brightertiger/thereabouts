"""Pinned unlocode records, retaining upstream identities and source evidence."""

import csv
import re
from collections.abc import Iterator
from pathlib import Path

from pipeline.config.source_options import Text as Options

from .contract import SourceContext
from .shared.lookup_rows import Row, point
from .shared.text import InputRow, publish_rows


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


def records(ctx: SourceContext) -> Iterator[InputRow]:
    for pin in ctx.pin.files:
        if pin.metadata.get("key", pin.name) != "code-list.csv":
            continue
        with ctx.input(pin.name).open(encoding="utf-8-sig", newline="") as stream:
            for ordinal, raw in enumerate(csv.DictReader(stream), 1):
                yield InputRow("trade_locations", pin, ordinal, raw)


def normalize(ctx: SourceContext) -> list[Path]:
    ctx.named("code-list.csv")
    return publish_rows(ctx, records(ctx), lambda row: trade(row.raw))


__all__ = ["Options", "normalize"]

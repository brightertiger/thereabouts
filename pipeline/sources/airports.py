"""Pinned airports records, retaining upstream identities and source evidence."""

import csv
from collections.abc import Iterator
from pathlib import Path

from pipeline.config.schema import H3

from .contract import SourceContext
from .shared.lookup_rows import Row, point
from .shared.text import InputRow, publish_rows


def airport(raw: dict[str, str], *, grid: H3) -> Row:
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
        **point(raw.get("latitude_deg"), raw.get("longitude_deg"), grid=grid),
    }


def records(ctx: SourceContext) -> Iterator[InputRow]:
    for pin in ctx.pin.files:
        if pin.metadata.get("key", pin.name) != "airports.csv":
            continue
        with ctx.input(pin.name).open(encoding="utf-8-sig", newline="") as stream:
            for ordinal, raw in enumerate(csv.DictReader(stream), 1):
                yield InputRow("airports", pin, ordinal, raw)


def normalize(ctx: SourceContext) -> list[Path]:
    ctx.named("airports.csv")
    return publish_rows(ctx, records(ctx), lambda row: airport(row.raw, grid=ctx.grid))

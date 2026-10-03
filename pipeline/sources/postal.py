"""Pinned postal records, retaining upstream identities and source evidence."""

import csv
import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

from pipeline.config.source_options import Text as Options
from pipeline.config.sources import SourceSettings
from pipeline.pins.models import SourcePin

from .contract import SourceContext
from .proposals.resolve import propose as propose_pin
from .shared.lookup_rows import Reject, Row, point
from .shared.text import InputRow, publish_rows

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


def records(ctx: SourceContext) -> Iterator[InputRow]:
    for pin in ctx.pin.files:
        if not pin.name.endswith(".zip"):
            continue
        ordinal = 0
        with zipfile.ZipFile(ctx.input(pin.name)) as archive:
            for member in archive.namelist():
                if not member.endswith(".txt") or "readme" in member.lower():
                    continue
                with (
                    archive.open(member) as data,
                    io.TextIOWrapper(data, encoding="utf-8-sig") as stream,
                ):
                    for raw in csv.reader(
                        stream, delimiter="\t", quoting=csv.QUOTE_NONE
                    ):
                        ordinal += 1
                        yield InputRow(
                            "postal_codes",
                            pin,
                            ordinal,
                            {"fields": raw, "member": member},
                        )


def normalize(ctx: SourceContext) -> list[Path]:
    return publish_rows(
        ctx,
        records(ctx),
        lambda row: postal(
            row.raw["fields"], str(row.pin.metadata.get("key", row.pin.name))
        ),
    )


__all__ = ["Options", "normalize", "propose"]


def propose(settings: SourceSettings) -> SourcePin:
    """Resolve upstream only for an explicit pin proposal."""
    return propose_pin(settings)

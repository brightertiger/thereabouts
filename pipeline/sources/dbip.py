"""Pinned dbip records, retaining upstream identities and source evidence."""

import csv
import gzip
import ipaddress
from collections.abc import Iterator
from pathlib import Path

from pipeline.config.schema import H3
from pipeline.config.source_options import Text as Options
from pipeline.config.sources import SourceSettings
from pipeline.pins.models import SourcePin

from .contract import SourceContext
from .proposals.resolve import propose as propose_pin
from .shared.lookup_rows import Reject, Row, point
from .shared.text import InputRow, publish_rows


def ip_range(raw: list[str], *, grid: H3) -> Row:
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
        **point(raw[6], raw[7], grid=grid),
    )


def records(ctx: SourceContext) -> Iterator[InputRow]:
    for pin in ctx.pin.files:
        if not pin.name.endswith(".gz"):
            continue
        count = 0
        with gzip.open(ctx.input(pin.name), "rt", encoding="utf-8") as stream:
            for count, raw in enumerate(csv.reader(stream), 1):
                yield InputRow("ip_ranges", pin, count, {"fields": raw})
        expected = pin.metadata.get("publisher_rows")
        if expected is not None and count != expected:
            raise ValueError("DB-IP rows disagree with the pinned publisher count")


def normalize(ctx: SourceContext) -> list[Path]:
    return publish_rows(
        ctx,
        records(ctx),
        lambda row: ip_range(row.raw["fields"], grid=ctx.runtime.config.h3),
    )


__all__ = ["Options", "normalize", "propose"]


def propose(settings: SourceSettings) -> SourcePin:
    """Resolve upstream only for an explicit pin proposal."""
    return propose_pin(settings)

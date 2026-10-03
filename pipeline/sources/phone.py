"""libphonenumber territories and localized geographic descriptions."""

import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from pipeline.config.source_options import Text as Options
from pipeline.config.sources import SourceSettings
from pipeline.pins.models import SourcePin

from .contract import SourceContext
from .proposals.resolve import propose as propose_pin
from .shared.lookup_rows import Reject, Row
from .shared.text import InputRow, publish_rows


def territories(path: Path) -> list[Row]:
    root = ET.parse(path).getroot()
    return [
        {**node.attrib, "metadata_xml": ET.tostring(node, encoding="unicode")}
        for node in root.findall("./territories/territory")
    ]


def metadata(raw: Row) -> Row:
    return dict(
        territory=raw["id"],
        calling_code=raw["countryCode"],
        leading_digits=raw.get("leadingDigits"),
        national_prefix=raw.get("nationalPrefix"),
        international_prefix=raw.get("internationalPrefix"),
        metadata_xml=raw["metadata_xml"],
    )


def prefix(raw: Row, name: str, countries: dict[str, list[str]]) -> Row:
    values = raw["fields"]
    if len(values) != 2 or not values[0].isdigit():
        raise Reject("Expected numeric prefix and geographic description")
    # Shared calling codes deliberately retain all candidate territories. A later
    # linking stage can refine NANPA prefixes; descriptions are not geocoded here.
    candidates = [code for code in countries if values[0].startswith(code)]
    calling = max(candidates, key=len) if candidates else None
    return dict(
        prefix=values[0],
        description=values[1],
        calling_code=calling,
        country_codes=countries.get(calling or "", []),
        language=Path(name).parent.name,
    )


def records(ctx: SourceContext) -> Iterator[InputRow]:
    for pin in ctx.pin.files:
        name = str(pin.metadata.get("key", pin.name))
        path = ctx.input(pin.name)
        if name.endswith("PhoneNumberMetadata.xml"):
            for ordinal, raw in enumerate(territories(path), 1):
                yield InputRow("phone_metadata", pin, ordinal, raw)
        elif name.startswith("resources/geocoding/"):
            with path.open(encoding="utf-8-sig") as stream:
                ordinal = 0
                for line in stream:
                    if line.strip() and not line.startswith("#"):
                        ordinal += 1
                        yield InputRow(
                            "phone_prefixes",
                            pin,
                            ordinal,
                            {
                                "fields": line.rstrip("\n").split("|", 1),
                            },
                        )


def normalize(ctx: SourceContext) -> list[Path]:
    pin = ctx.named("resources/PhoneNumberMetadata.xml")
    countries: dict[str, list[str]] = defaultdict(list)
    for row in territories(ctx.input(pin.name)):
        countries[row["countryCode"]].append(row["id"])

    def convert(item: InputRow) -> Row:
        if item.kind == "phone_metadata":
            return metadata(item.raw)
        return prefix(
            item.raw, str(item.pin.metadata.get("key", item.pin.name)), countries
        )

    return publish_rows(ctx, records(ctx), convert)


__all__ = ["Options", "normalize", "propose"]


def propose(settings: SourceSettings) -> SourcePin:
    """Resolve upstream only for an explicit pin proposal."""
    return propose_pin(settings)

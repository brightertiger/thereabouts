"""libphonenumber territories and localized geographic descriptions."""

import xml.etree.ElementTree as ET
from pathlib import Path

from .lookup_rows import Reject, Row


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

"""Small loss-aware GeoNames TSV parsers; selection remains broad."""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Mapping
from typing import cast

from .geonames_download import BASE_URL, LICENSE_URL

Row = dict[str, object]
KEPT_CLASSES = frozenset({"A", "P"})
LICENSE = "CC-BY-4.0"
BUILDER_VERSION = "geonames-1"
POLICY_VERSION = "all-P-and-A-all-aliases-1"
MAX_LINE_BYTES = 1_000_000


def text(value: str) -> str | None:
    """Normalize Unicode and whitespace; do not infer language from ASCII."""
    return unicodedata.normalize("NFC", " ".join(value.split())) or None


def integer(value: str, field: str, *, positive: bool = False) -> int:
    number = int(value)
    if number < (1 if positive else 0) or number > 2**63 - 1:
        raise ValueError(f"Invalid {field}: {value}")
    return number


def fields(raw: bytes, count: int) -> list[str]:
    if len(raw) > MAX_LINE_BYTES:
        raise ValueError("TSV line exceeds the 1 MB audited row limit")
    values = raw.decode("utf-8").rstrip("\r\n").split("\t")
    if len(values) != count:
        raise ValueError(f"Expected {count} fields, got {len(values)}")
    return values


def provenance(pin: Mapping[str, object], extra: Mapping[str, object]) -> str:
    return json.dumps(
        {
            "source_url": str(pin.get("url", BASE_URL)),
            "license_url": LICENSE_URL,
            "attribution": "GeoNames (www.geonames.org), CC BY 4.0",
            "input_sha256": pin["sha256"],
            "retrieved_at": pin["retrieved_at"],
            "last_modified": pin.get("last_modified"),
            **extra,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def place(raw: bytes, release: str, pin: Mapping[str, object]) -> Row | None:
    values = fields(raw, 19)
    if values[6] not in KEPT_CLASSES:
        return None
    source_id = integer(values[0], "geonameid", positive=True)
    name = text(values[1]) or text(values[2])
    if name is None:
        raise ValueError("Missing Unicode name and asciiname")
    latitude, longitude = float(values[4]), float(values[5])
    if not (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        raise ValueError("Invalid WGS84 point")
    country = text(values[8])
    if country is not None and (
        len(country) != 2
        or not country.isascii()
        or not country.isalpha()
        or country != country.upper()
    ):
        raise ValueError(f"Invalid country code {country}")
    population = integer(values[14], "population") if values[14] else None
    extra: Row = {
        "asciiname": values[2],
        "alternate_names_untyped": values[3],
        "cc2": values[9],
        "admin3_code": values[12],
        "admin4_code": values[13],
        "timezone": values[17],
        "modification_date": values[18],
        "feature_class": values[6],
        "feature_code": values[7],
        "admin_level": values[7][3:] if values[7].startswith("ADM") else None,
        "name_raw": values[1],
        "name_fallback_ascii": not bool(text(values[1])),
    }
    return {
        "source": "geonames",
        "source_id": str(source_id),
        "kind": "settlement" if values[6] == "P" else "administrative",
        "name": name,
        "name_en": None,
        "latitude": latitude,
        "longitude": longitude,
        "feature_class": values[6],
        "feature_code": text(values[7]),
        "subtype": text(values[7]),
        "country_code": country,
        "admin1_code": text(values[10]),
        "admin2_code": text(values[11]),
        "parent_source_id": None,
        "population": population,
        "source_release": release,
        "license": LICENSE,
        "provenance": provenance(pin, extra),
    }


def alias(raw: bytes, release: str, pin: Mapping[str, object]) -> Row:
    values = fields(raw, 10)
    source_id = integer(values[0], "alternateNameId", positive=True)
    entity_id = integer(values[1], "geonameid", positive=True)
    name = text(values[3])
    if name is None:
        raise ValueError("Empty alternate name")
    if any(flag not in ("", "0", "1") for flag in values[4:8]):
        raise ValueError("Unexpected alternate-name boolean flag")
    return {
        "source": "geonames",
        "source_id": str(source_id),
        "entity_source_id": str(entity_id),
        "name": name,
        "language": text(values[2]),
        "name_kind": "alternate",
        "is_preferred": values[4] == "1",
        "is_short": values[5] == "1",
        "is_colloquial": values[6] == "1",
        "is_historic": values[7] == "1",
        "valid_from": text(values[8]),
        "valid_to": text(values[9]),
        "source_release": release,
        "license": LICENSE,
        "provenance": provenance(
            pin,
            {
                "name_raw": values[3],
                "language_raw": values[2],
                "valid_from_raw": values[8],
                "valid_to_raw": values[9],
            },
        ),
    }


def english_rank(row: Row) -> tuple[int, int] | None:
    """Convenience English label only; every alias remains in the names output."""
    if (
        row["language"] != "en"
        or row["is_historic"]
        or row["is_colloquial"]
        or row["valid_to"] is not None
        or row["valid_from"] is not None
    ):
        return None
    return (0 if row["is_preferred"] else 1, int(cast(str, row["source_id"])))

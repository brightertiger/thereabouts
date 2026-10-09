"""Small loss-aware GeoNames TSV parsers; selection remains broad."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

from pipeline.sources.shared.rows import (
    RowRejected,
    canonical_json,
    clean_text,
    provenance,
)

from .tsv import fields

Row = dict[str, object]


def text(value: str) -> str | None:
    """Collapse whitespace, then NFC; do not infer language from ASCII."""
    return clean_text(value, order="split_first")


def integer(value: str, field: str, *, positive: bool = False) -> int:
    number = int(value)
    if number < (1 if positive else 0) or number > 2**63 - 1:
        raise RowRejected(f"Invalid {field}: {value}")
    return number


def provenance_json(pin: Mapping[str, object], extra: Mapping[str, object]) -> str:
    """Insertion-ordered JSON, the spelling GeoNames rows have always carried."""
    return canonical_json(
        provenance(
            str(pin["url"]),
            pin["license_url"],
            pin["attribution"],
            {
                "input_sha256": pin["sha256"],
                "retrieved_at": pin["retrieved_at"],
                "last_modified": pin.get("last_modified"),
            },
            extra,
        ),
        sort_keys=False,
    )


def place(raw: bytes, release: str, pin: Mapping[str, object]) -> Row | None:
    values = fields(raw, 19)
    if values[6] not in cast(list[str], pin["kept_classes"]):
        return None
    source_id = integer(values[0], "geonameid", positive=True)
    name = text(values[1]) or text(values[2])
    if name is None:
        raise RowRejected("Missing Unicode name and asciiname")
    latitude, longitude = float(values[4]), float(values[5])
    if not (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        raise RowRejected("Invalid WGS84 point")
    country = text(values[8])
    if country is not None and (
        len(country) != 2
        or not country.isascii()
        or not country.isalpha()
        or country != country.upper()
    ):
        raise RowRejected(f"Invalid country code {country}")
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
        "license": pin["license"],
        "provenance": provenance_json(pin, extra),
    }


def alias(raw: bytes, release: str, pin: Mapping[str, object]) -> Row:
    values = fields(raw, 10)
    source_id = integer(values[0], "alternateNameId", positive=True)
    entity_id = integer(values[1], "geonameid", positive=True)
    name = text(values[3])
    if name is None:
        raise RowRejected("Empty alternate name")
    if any(flag not in ("", "0", "1") for flag in values[4:8]):
        raise RowRejected("Unexpected alternate-name boolean flag")
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
        "license": pin["license"],
        "provenance": provenance_json(
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

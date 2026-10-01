"""Overture rows."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

import shapely

from . import fingerprint
from .overture import LICENSE_URL, SOURCE


class RowRejectedError(ValueError):
    """An unusable source feature, distinct from a failed output publication."""


def text(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(unicodedata.normalize("NFC", str(value)).split())
    return result or None


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Unexpected JSON value: {type(value)}")


def encode(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _labels(row: dict[str, Any]) -> tuple[str | None, str | None]:
    names = _mapping(row.get("names"))
    return text(names.get("primary")), text(_mapping(names.get("common")).get("en"))


def _provenance(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        **context,
        "license_url": LICENSE_URL,
        "attribution": (
            "Overture Maps Foundation; OpenStreetMap contributors; "
            "upstream sources retained below"
        ),
        "upstream": {key: value for key, value in row.items() if key != "geometry"},
        "transformations": [
            "NFC and whitespace display names",
            "all source classifications retained",
        ],
    }


def _common(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": SOURCE,
        "source_id": row["id"],
        "source_release": context["source_release"],
        "license": "ODbL-1.0",
    }


def place(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    geometry = shapely.from_wkb(row["geometry"])
    if geometry.is_empty or geometry.geom_type != "Point" or not geometry.is_valid:
        raise RowRejectedError("invalid or non-point division geometry")
    if not (-180 <= geometry.x <= 180 and -90 <= geometry.y <= 90):
        raise RowRejectedError("division coordinates outside WGS84")
    if row.get("population") is not None and row["population"] < 0:
        raise RowRejectedError("negative population")
    name, english = _labels(row)
    if name is None:
        raise RowRejectedError("division lacks required primary name")
    return {
        **_common(row, context),
        "kind": row["subtype"],
        "name": name,
        "name_en": english,
        "latitude": geometry.y,
        "longitude": geometry.x,
        "feature_class": text(row.get("class")),
        "feature_code": None,
        "subtype": row["subtype"],
        "country_code": text(row.get("country")),
        "admin1_code": text(row.get("region")),
        "admin2_code": None,
        "parent_source_id": row.get("parent_division_id"),
        "population": row.get("population"),
        "provenance": encode(_provenance(row, context)),
    }


def names(row: dict[str, Any], context: dict[str, Any]) -> Iterator[dict[str, Any]]:
    source_names = _mapping(row.get("names"))
    candidates: list[dict[str, Any]] = []
    if source_names.get("primary"):
        candidates.append({"value": source_names["primary"], "variant": "primary"})
    candidates.extend(
        {"value": value, "language": language, "variant": "common"}
        for language, value in sorted(_mapping(source_names.get("common")).items())
    )
    candidates.extend(source_names.get("rules") or [])
    for index, rule in enumerate(candidates):
        name = text(rule.get("value"))
        if name is None:
            raise RowRejectedError("empty source alias")
        variant = text(rule.get("variant")) or "rule"
        provenance = {
            **context,
            "license_url": LICENSE_URL,
            "attribution": "Overture Maps Foundation; upstream division sources",
            "upstream_name_rule": rule,
            "source_record_id": row["id"],
            "transformations": ["NFC and whitespace"],
        }
        yield {
            **_common(row, context),
            "source_id": fingerprint(
                {"entity": row["id"], "index": index, "rule": json.loads(encode(rule))}
            ),
            "entity_source_id": row["id"],
            "name": name,
            "language": text(rule.get("language")),
            "name_kind": variant,
            "is_preferred": variant in ("primary", "common"),
            "is_short": variant == "short",
            "is_colloquial": variant == "colloquial",
            "is_historic": variant in ("historic", "historical"),
            "valid_from": text(rule.get("valid_from")),
            "valid_to": text(rule.get("valid_to")),
            "provenance": encode(provenance),
        }

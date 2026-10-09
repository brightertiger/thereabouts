"""Overture rows."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

import shapely

from pipeline.runtime.jsonio import digest
from pipeline.sources.shared.rows import (
    RowRejected,
    canonical_json,
    clean_text,
    provenance,
)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Unexpected JSON value: {type(value)}")


def encode(value: Any) -> str:
    """Canonical JSON that also writes upstream dates as ISO 8601."""
    return canonical_json(value, default=_json_default)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _labels(row: dict[str, Any]) -> tuple[str | None, str | None]:
    names = _mapping(row.get("names"))
    english = _mapping(names.get("common")).get("en")
    return clean_text(names.get("primary")), clean_text(english)


def _provenance(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return provenance(
        context["source_url"],
        context["license_url"],
        context["attribution"],
        context,
        {
            "upstream": {key: value for key, value in row.items() if key != "geometry"},
            "transformations": [
                "NFC and whitespace display names",
                "all source classifications retained",
            ],
        },
    )


def _common(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "overture",
        "source_id": row["id"],
        "source_release": context["source_release"],
        "license": context["license"],
    }


def place(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    geometry = shapely.from_wkb(row["geometry"])
    if geometry.is_empty or geometry.geom_type != "Point" or not geometry.is_valid:
        raise RowRejected("invalid or non-point division geometry")
    if not (-180 <= geometry.x <= 180 and -90 <= geometry.y <= 90):
        raise RowRejected("division coordinates outside WGS84")
    if row.get("population") is not None and row["population"] < 0:
        raise RowRejected("negative population")
    name, english = _labels(row)
    if name is None:
        raise RowRejected("division lacks required primary name")
    return {
        **_common(row, context),
        "kind": row["subtype"],
        "name": name,
        "name_en": english,
        "latitude": geometry.y,
        "longitude": geometry.x,
        "feature_class": clean_text(row.get("class")),
        "feature_code": None,
        "subtype": row["subtype"],
        "country_code": clean_text(row.get("country")),
        "admin1_code": clean_text(row.get("region")),
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
        name = clean_text(rule.get("value"))
        if name is None:
            raise RowRejected("empty source alias")
        variant = clean_text(rule.get("variant")) or "rule"
        evidence = provenance(
            context["source_url"],
            context["license_url"],
            context["attribution"],
            context,
            {
                "upstream_name_rule": rule,
                "source_record_id": row["id"],
                "transformations": ["NFC and whitespace"],
            },
        )
        yield {
            **_common(row, context),
            "source_id": digest(
                {"entity": row["id"], "index": index, "rule": json.loads(encode(rule))}
            ),
            "entity_source_id": row["id"],
            "name": name,
            "language": clean_text(rule.get("language")),
            "name_kind": variant,
            "is_preferred": variant in ("primary", "common"),
            "is_short": variant == "short",
            "is_colloquial": variant == "colloquial",
            "is_historic": variant in ("historic", "historical"),
            "valid_from": clean_text(rule.get("valid_from")),
            "valid_to": clean_text(rule.get("valid_to")),
            "provenance": encode(evidence),
        }

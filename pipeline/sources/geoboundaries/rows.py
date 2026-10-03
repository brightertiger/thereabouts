"""Geoboundaries rows."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from shapely.geometry.base import BaseGeometry

from pipeline.sources.shared.geometry import bounds_columns
from pipeline.sources.shared.schemas import SCHEMA_HASHES


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = " ".join(unicodedata.normalize("NFC", str(value)).split())
    return result if result and result.lower() not in {"none", "null", "nan"} else None


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _row(
    properties: dict[str, Any],
    geometry: BaseGeometry,
    pin: dict[str, Any],
    country: str | None,
    index: int,
    part: int,
    transformations: list[str],
    kinds: dict[str, str],
) -> dict[str, object]:
    metadata = pin["metadata"]
    unit = f"{metadata['boundaryISO']}-{metadata['boundaryType']}"
    identifier = (
        _text(properties.get("shapeID")) or f"{metadata['boundaryID']}:record:{index}"
    )
    level = str(metadata["boundaryType"])
    iso = _text(properties.get("shapeISO"))
    subdivision = (
        iso
        if iso
        and country
        and re.fullmatch(r"[A-Z]{2}-[A-Z0-9]{1,3}", iso)
        and iso.startswith(country + "-")
        else None
    )
    license_url = (
        _text(metadata.get("licenseSource"))
        or "https://www.geoboundaries.org/index.html#citation"
    )
    if not license_url.startswith(("http://", "https://")):
        license_url = "https://" + license_url
    provenance = {
        "source_url": pin["url"],
        "license_url": license_url,
        "attribution": "geoBoundaries; " + str(metadata["boundarySource"]),
        "layer_metadata": metadata,
        "source_properties": properties,
        "commit": pin["commit"],
        "retrieved_at": pin["retrieved_at"],
        "archive_sha256": pin["archive_sha256"],
        "record_index": index,
        "geometry_part": part,
        "transformations": transformations,
        "name_language": None,
        "schema_hash": SCHEMA_HASHES["areas"],
        "country_code_mapping": "GeoNames countryInfo ISO3/ISO2; XK user-assigned",
        "country_reference": {
            "source_url": "https://download.geonames.org/export/dump/countryInfo.txt",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": "GeoNames",
        },
        "layer_unit": unit,
    }
    return {
        "source": "geoboundaries",
        "source_id": identifier,
        "entity_id": identifier,
        "kind": kinds[level],
        "subtype": _text(properties.get("shapeType")) or level,
        "admin_level": level,
        "parent_source_id": None,
        "country_code": country,
        "subdivision_code": subdivision,
        "name": _text(properties.get("shapeName")),
        "name_en": None,
        "geometry": geometry.wkb,
        **bounds_columns(geometry),
        "is_land": None,
        "is_territorial": None,
        "source_release": pin["commit"],
        "license": _text(metadata["boundaryLicense"]) or "Unspecified by source",
        "provenance": _json(provenance),
    }

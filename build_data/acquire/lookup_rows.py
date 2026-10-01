"""Conservative cleaning and point keys shared only by additional lookups."""

import json
import math
import unicodedata
from typing import Any

import h3

Row = dict[str, Any]


class Reject(ValueError):
    """A structurally unreadable source record, recorded in the rejection audit."""


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(unicodedata.normalize("NFC", value).split()) or None


def point(latitude: str | float | None, longitude: str | float | None) -> Row:
    result: Row = dict(
        latitude=None, longitude=None, h3=None, h3_uint64=None, h3_resolution=None
    )
    if latitude in (None, "") and longitude in (None, ""):
        return result
    try:
        lat, lon = float(str(latitude)), float(str(longitude))
        if not (
            math.isfinite(lat)
            and math.isfinite(lon)
            and -90 <= lat <= 90
            and -180 <= lon <= 180
        ):
            raise ValueError("out of range")
    except ValueError:
        result["coordinate_error"] = "invalid coordinates retained in provenance"
        return result
    cell = h3.latlng_to_cell(lat, lon, 8)
    return dict(
        latitude=lat,
        longitude=lon,
        h3=cell,
        h3_uint64=h3.str_to_int(cell),
        h3_resolution=8,
    )


def decorate(
    row: Row, source: str, identity: str, pin: Row, release: str, raw: object
) -> Row:
    error = row.pop("coordinate_error", None)
    for key, value in row.items():
        if isinstance(value, str):
            row[key] = clean(value)
    country = row.get("country_code")
    if country and (
        len(country) != 2 or not country.isascii() or not country.isalpha()
    ):
        row["country_code"] = None
    elif country:
        row["country_code"] = country.upper()
    row.update(
        source=source,
        source_id=identity,
        source_release=release,
        license=pin["license"],
        provenance=json.dumps(
            {
                "source_url": pin["url"],
                "license_url": pin["license_url"],
                "attribution": pin["attribution"],
                "retrieved_at": pin["retrieved_at"],
                "coordinate_error": error,
                "raw": raw,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    return row

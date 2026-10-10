"""Conservative cleaning and point keys shared only by additional lookups."""

import math
from typing import Any

import h3

from pipeline.config.schema import H3

from .rows import canonical_json, clean_text, provenance

Row = dict[str, Any]


def point(
    latitude: str | float | None, longitude: str | float | None, *, grid: H3
) -> Row:
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
    cell = h3.latlng_to_cell(lat, lon, grid.cell_resolution)
    return dict(
        latitude=lat,
        longitude=lon,
        h3=cell,
        h3_uint64=h3.str_to_int(cell),
        h3_resolution=grid.cell_resolution,
    )


def decorate(
    row: Row, source: str, identity: str, pin: Row, release: str, raw: object
) -> Row:
    error = row.pop("coordinate_error", None)
    for key, value in row.items():
        if isinstance(value, str):
            row[key] = clean_text(value)
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
        provenance=canonical_json(
            provenance(
                pin["url"],
                pin["license_url"],
                pin["attribution"],
                {
                    "retrieved_at": pin["retrieved_at"],
                    "coordinate_error": error,
                    "raw": raw,
                },
            ),
            sort_keys=False,
            allow_nan=True,
        ),
    )
    return row

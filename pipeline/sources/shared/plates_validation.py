"""Semantic validation of the plate evidence contracts."""

import math
import re
from typing import Any


def validate_plate(row: dict[str, Any], kind: str) -> None:
    if (
        not row.get("country_code")
        or not row.get("source_url")
        or not row.get("retrieved_at")
    ):
        raise ValueError("Plate evidence needs country, source URL and retrieval date")
    if kind == "plate_survey":
        if row["classification"] not in (
            "usable_now",
            "historic_only",
            "printed_not_encoded",
            "none",
            "unverified",
        ):
            raise ValueError("Invalid survey classification")
        if row["classification"] != "unverified" and not row.get("evidence"):
            raise ValueError("Survey classification requires fetched evidence")
    else:
        if row.get("series_status") not in ("current", "historic", "unknown"):
            raise ValueError("Invalid series status")
        if kind == "plate_codes":
            if not row.get("code") or not row.get("evidence_locator"):
                raise ValueError("Plate code requires a source locator")
            lat, lon = row.get("latitude"), row.get("longitude")
            if (lat is None) != (lon is None):
                raise ValueError("Incomplete plate coordinates")
            if (
                lat is not None
                and lon is not None
                and not (
                    math.isfinite(lat)
                    and math.isfinite(lon)
                    and -90 <= lat <= 90
                    and -180 <= lon <= 180
                )
            ):
                raise ValueError("Invalid plate coordinates")
        elif kind == "plate_formats":
            pattern = re.compile(row["pattern"])
            if row.get("code_group") and row["code_group"] not in pattern.groupindex:
                raise ValueError("Missing place-code capture group")
            if any(pattern.fullmatch(example) is None for example in row["examples"]):
                raise ValueError("Source specimen does not match plate grammar")

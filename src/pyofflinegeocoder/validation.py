"""Input validation shared by scalar and streamed queries."""

import math
from numbers import Real


def number(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite real number, not a boolean")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def coordinate(lat: float, lon: float) -> tuple[float, float]:
    lat, lon = number(lat, "latitude"), number(lon, "longitude")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("latitude must be in [-90, 90], longitude in [-180, 180]")
    return lat, -180.0 if lon == 180 else lon


def options(include_place: bool, cutoff: float | None) -> float | None:
    if not isinstance(include_place, bool):
        raise ValueError("include_place must be boolean")
    if cutoff is not None:
        cutoff = number(cutoff, "max_place_distance_km")
        if cutoff < 0:
            raise ValueError("max_place_distance_km must be nonnegative")
    return cutoff

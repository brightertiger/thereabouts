"""Normalize input once, before addressing the reference cell."""

import math
from collections.abc import Iterable, Mapping
from numbers import Real
from typing import Literal, cast

from h3.api import basic_int as h3

from ..client_errors import InvalidInputError
from ..results import Query

BATCH_SIZE = 4096
Errors = Literal["raise", "collect"]


def coordinate_values(value: object) -> tuple[float, float]:
    if type(value) not in (tuple, list) and (
        not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping))
    ):
        raise InvalidInputError("Expected a latitude/longitude pair")
    try:
        latitude, longitude = cast(Iterable[object], value)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError("Expected a latitude/longitude pair") from exc
    numbers = []
    for name, item, limit in (
        ("latitude", latitude, 90),
        ("longitude", longitude, 180),
    ):
        if type(item) not in (float, int) and (
            isinstance(item, bool) or not isinstance(item, Real)
        ):
            raise InvalidInputError(f"{name} must be a finite real number")
        try:
            number = float(cast(Real, item))
        except OverflowError as exc:
            raise InvalidInputError(f"{name} is outside the numeric range") from exc
        if not math.isfinite(number) or not -limit <= number <= limit:
            raise InvalidInputError(f"{name} must be finite and within ±{limit}")
        numbers.append(number)
    lat, lon = numbers
    if lon == 180:
        lon = -180.0
    return lat, lon


def coordinates(value: object) -> tuple[int, Query]:
    lat, lon = coordinate_values(value)
    return int(h3.latlng_to_cell(lat, lon, 8)), Query("coordinates", lat, lon)


def h3_value(value: object) -> int:
    if (
        not isinstance(value, str)
        or len(value) != 15
        or any(char not in "0123456789abcdefABCDEF" for char in value)
    ):
        raise InvalidInputError("Expected a resolution-8 H3 hexadecimal string")
    cell = int(value, 16)
    if not h3.is_valid_cell(cell) or h3.get_resolution(cell) != 8:
        raise InvalidInputError("Only valid resolution-8 H3 cells are supported")
    return cell


def h3_cell(value: object) -> tuple[int, Query]:
    cell = h3_value(value)
    return cell, Query("h3", h3=f"{cell:x}")


def batch_options(errors: Errors, chunk_size: int) -> None:
    if errors not in ("raise", "collect"):
        raise InvalidInputError("errors must be 'raise' or 'collect'")
    if type(chunk_size) is not int or chunk_size < 1:
        raise InvalidInputError("chunk_size must be a positive integer")

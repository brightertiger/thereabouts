"""Vector results compare exactly, except coordinates within 1e-9 degrees.

Points come from libm trigonometry (H3 cell centres), whose last bit differs
between x86_64 and ARM: at most 1.4e-14 degrees was observed. Every other value,
including key sets, list lengths and other floats, must match exactly.
"""

import math
from typing import Any

COORDINATE_TOLERANCE = 1e-9
COORDINATES = frozenset({"lat", "lon"})


def difference(actual: Any, expected: Any, path: str = "$") -> str | None:
    """Return the first differing path, or None when the values agree."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            return f"{path}: {actual!r} != {expected!r}"
        for key, value in expected.items():
            if (
                key in COORDINATES
                and isinstance(value, float)
                and isinstance(actual[key], float)
            ):
                if not math.isclose(
                    actual[key], value, rel_tol=0, abs_tol=COORDINATE_TOLERANCE
                ):
                    return f"{path}.{key}: {actual[key]!r} != {value!r}"
            elif found := difference(actual[key], value, f"{path}.{key}"):
                return found
        return None
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return f"{path}: {actual!r} != {expected!r}"
        for i, (left, right) in enumerate(zip(actual, expected, strict=True)):
            if found := difference(left, right, f"{path}[{i}]"):
                return found
        return None
    return None if actual == expected else f"{path}: {actual!r} != {expected!r}"


def assert_same(actual: Any, expected: Any, label: object = "") -> None:
    if found := difference(actual, expected):
        raise AssertionError(f"{label}: {found}")

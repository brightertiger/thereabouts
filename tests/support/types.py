"""Types of the immutable synthetic reference fixture."""

from typing import Any, TypeAlias

BBox: TypeAlias = tuple[float, float, float, float] | list[float]
Audit: TypeAlias = list[dict[str, Any]]

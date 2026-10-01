"""The public answer."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Location:
    city: str | None
    state: str | None
    country: str | None
    country_code: str | None

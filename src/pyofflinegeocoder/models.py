"""Immutable public answers, with administration separate from settlement context."""

from dataclasses import dataclass
from typing import Literal

AdminStatus = Literal["matched", "ambiguous", "not_applicable", "no_coverage"]
AdminMethod = Literal["uniform_cell", "polygon", "none"]
PlaceStatus = Literal[
    "matched", "beyond_distance", "outside_land", "no_coverage", "disabled"
]
LandStatus = Literal["inside_mask", "outside_mask", "unknown"]


@dataclass(frozen=True)
class Admin:
    """A source administrative identity; code is ISO only when supplied."""

    id: str
    name: str
    code: str | None
    source: str


@dataclass(frozen=True)
class AdminMatch:
    """Containment status and all candidates, sorted by stable source ID."""

    status: AdminStatus
    value: Admin | None
    candidates: tuple[Admin, ...]
    method: AdminMethod


@dataclass(frozen=True)
class Place:
    """A settlement and spherical distance, retaining its source admin codes."""

    geoname_id: int
    name: str
    feature_code: str
    latitude: float
    longitude: float
    distance_km: float
    source_country_code: str | None
    source_admin1_code: str | None


@dataclass(frozen=True)
class ReverseResult:
    """Original-point administration and independent nearby settlement context."""

    latitude: float
    longitude: float
    country: AdminMatch
    admin1: AdminMatch
    nearest_place: Place | None
    place_status: PlaceStatus
    land_status: LandStatus
    snapshot_id: str
    policy_id: str


@dataclass(frozen=True)
class DatasetInfo:
    """Frozen snapshot identity, coverage and attribution."""

    snapshot_id: str
    schema_version: str
    source_dates: tuple[tuple[str, str], ...]
    policy_id: str
    coverage_description: str
    attribution: tuple[str, ...]

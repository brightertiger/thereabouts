"""Immutable place context and detached JSON serialization."""

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Any, Literal

from .client_errors import AmbiguousResultError

Status = Literal[
    "matched",
    "ambiguous",
    "not_found",
    "unassigned",
    "ineligible",
    "outside_coverage",
    "invalid_input",
]
Json = str | int | float | bool | None | tuple["Json", ...] | Mapping[str, "Json"]


def freeze(value: Any) -> Json:
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("Expected JSON data")


def freeze_object(value: dict[str, Any]) -> Mapping[str, Json]:
    return MappingProxyType({key: freeze(item) for key, item in value.items()})


def plain(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: plain(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Evidence:
    golden_table: str
    source_ids: Json
    name_provenance: Json


@dataclass(frozen=True, slots=True)
class Place:
    id: str
    name: str
    name_en: str | None
    local_name: str | None
    role: str
    settlement_kind: str
    country_code: str
    code: str | None
    code_status: str | None
    code_system: str | None
    country_id: str | None
    parent_id: str | None
    sovereign_id: str | None
    normalized_city_id: str | None
    parent_method: str | None
    normalization_method: str | None
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class Methods:
    city: str | None
    state: str | None
    country: str | None
    land: str


@dataclass(frozen=True, slots=True)
class Confidence:
    basis: str
    calibrated_probability: None = None


@dataclass(frozen=True, slots=True)
class Distance:
    """A policy band at the reference centre, never a measured point distance."""

    greater_than_m: int | None
    at_most_m: int
    cutoff_m: int
    exact_m: None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    place: "Place | SourcePlace | None"
    city: Place | None
    state: Place | None
    country: Place | None
    sovereign: Place | None
    relationship: str
    methods: Methods
    confidence: Confidence
    distance: Distance | None
    accuracy_m: None = None
    observations: tuple["Observation", ...] = ()


@dataclass(frozen=True, slots=True)
class Query:
    kind: Literal["coordinates", "h3", "postal", "airport"]
    latitude: float | None = None
    longitude: float | None = None
    h3: str | None = None
    value: str | None = None
    country: str | None = None
    scheme: str | None = None


@dataclass(frozen=True, slots=True)
class Reference:
    h3: str
    resolution: int
    stored_h3: str | None
    stored_resolution: int | None
    quantization: str = "r8-centre-logical-ancestors"


@dataclass(frozen=True, slots=True)
class SourcePlace:
    id: str
    name: str | None
    role: str
    country_code: str | None
    codes: Mapping[str, Json]
    type: str | None


@dataclass(frozen=True, slots=True)
class Observation:
    source: str
    source_id: str
    source_release: str
    license: str
    golden_table: str
    fields: Mapping[str, Json]
    reference: Reference | None
    country_id: str | None
    state_id: str | None
    city_id: str | None
    methods: Methods
    cell_status: str
    country_disagrees: bool | None


@dataclass(frozen=True, slots=True)
class Source:
    source: str
    release: str
    license: str
    attribution: str
    source_url: str
    license_url: str


@dataclass(frozen=True, slots=True)
class Data:
    family: str
    version: str
    catalogue_epoch: str
    manifest_sha256: str
    golden_sha256: str
    policy_sha256: str
    h3_version: str
    sources: tuple[Source, ...]


@dataclass(frozen=True, slots=True)
class Warning:
    code: str


@dataclass(frozen=True, slots=True)
class InputError:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Resolution:
    status: Status
    selected: Candidate | None
    candidates: tuple[Candidate, ...]
    query: Query
    reference: Reference | None
    data: Data
    warnings: tuple[Warning, ...] = ()
    error: InputError | None = None

    def require_one(self) -> Candidate | None:
        """Return a unique candidate, None for no match, or raise on ambiguity."""
        if self.status == "ambiguous":
            raise AmbiguousResultError("Multiple candidates remain")
        return self.selected

    def to_dict(self) -> dict[str, Any]:
        """Return a mutable JSON tree independent of this result and its reader."""
        result: dict[str, Any] = plain(self)
        return result

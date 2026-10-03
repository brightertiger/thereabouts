"""Frozen, detached result objects matching the Rust core's JSON contract."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Point:
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class Country:
    code: str
    code3: str | None
    name: str


@dataclass(frozen=True, slots=True)
class State:
    code: str | None
    name: str


@dataclass(frozen=True, slots=True)
class City:
    id: str
    name: str
    name_en: str | None
    kind: str
    population: int | None
    point: Point | None


@dataclass(frozen=True, slots=True)
class DistanceBand:
    greater_than_km: float
    at_most_km: float


@dataclass(frozen=True, slots=True)
class Evidence:
    stored_cell: str | None
    country_id: str | None
    state_id: str | None
    city_id: str | None
    city_method: str | None
    land_method: str | None
    reason: str | None
    timezones: tuple[str, ...]
    source_ids: tuple[tuple[tuple[str, str], ...], ...] | None


@dataclass(frozen=True, slots=True)
class Result:
    status: str
    kind: str
    match: str | None
    country: Country | None
    state: State | None
    city: City | None
    timezone: str | None
    point: Point | None
    cell: str | None
    distance_band: DistanceBand | None
    candidates: tuple["Result", ...]
    rank_basis: str | None
    evidence: Evidence | None = None
    hint: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Result":
        """Convert the native core's detached JSON tree without guessing fields."""
        data = value.copy()
        for field, kind in (
            ("country", Country),
            ("state", State),
            ("point", Point),
            ("distance_band", DistanceBand),
        ):
            if data[field] is not None:
                data[field] = kind(**data[field])
        if data["city"] is not None:
            city = data["city"].copy()
            if city["point"] is not None:
                city["point"] = Point(**city["point"])
            data["city"] = City(**city)
        data["candidates"] = tuple(map(cls.from_dict, data["candidates"]))
        if data.get("evidence") is not None:
            evidence = data["evidence"].copy()
            evidence["timezones"] = tuple(evidence["timezones"])
            if evidence["source_ids"] is not None:
                evidence["source_ids"] = tuple(
                    tuple(sorted(source.items())) for source in evidence["source_ids"]
                )
            data["evidence"] = Evidence(**evidence)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """Return snake_case JSON data, omitting evidence unless requested."""
        data = asdict(self)
        if self.hint is None:
            del data["hint"]
        data["candidates"] = [result.to_dict() for result in self.candidates]
        if self.evidence is None:
            del data["evidence"]
        else:
            data["evidence"]["timezones"] = list(self.evidence.timezones)
        if self.evidence is not None and self.evidence.source_ids is not None:
            data["evidence"]["source_ids"] = [
                dict(source) for source in self.evidence.source_ids
            ]
        return data

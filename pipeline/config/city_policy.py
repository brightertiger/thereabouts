"""Schemas for unchanged settlement eligibility and country city conventions."""

from dataclasses import dataclass, field


@dataclass
class Eligibility:
    minimum_population: int = 0
    typed_minimum: int = 0
    major_seats: list[str] = field(default_factory=list)
    seat_codes: list[str] = field(default_factory=list)
    excluded_codes: list[str] = field(default_factory=list)


@dataclass
class TownRadius:
    enabled: bool = False
    minimum_population: int = 0
    maximum_population: int = 0
    density_per_km2: int = 0
    minimum_km: float = 0.0
    maximum_km: float = 0.0


@dataclass
class Evidence:
    reason: str = ""
    reference: str = ""


@dataclass
class Footprint:
    city_id: str = ""
    members: list[str] = field(default_factory=list)
    area_entities: list[str] = field(default_factory=list)
    area_entity: str | None = None
    role: str | None = None
    priority: int = 0
    clip_urban: bool = False
    reason: str = ""
    reference: str = ""


@dataclass
class CountryCities:
    footprints: list[Footprint] = field(default_factory=list)
    parts: dict[str, str] = field(default_factory=dict)
    independent: list[str] = field(default_factory=list)
    identity_aliases: dict[str, str] = field(default_factory=dict)
    container_terms: list[str] = field(default_factory=list)
    excluded_areas: list[str] = field(default_factory=list)
    part_evidence: dict[str, Evidence] = field(default_factory=dict)
    alias_evidence: str = ""
    excluded_area_evidence: str = ""
    reason: str = ""
    reference: str = ""


@dataclass
class Cities:
    # Retained policy metadata survives conversion; it is not a builder version.
    version: str = ""
    pilot: list[str] = field(default_factory=list)
    eligibility: Eligibility = field(default_factory=Eligibility)
    core_m: int = 0
    population_floor: int = 0
    nearest_m: int = 0
    distant_m: int = 0
    town_radius: TownRadius = field(default_factory=TownRadius)
    countries: dict[str, CountryCities] = field(default_factory=dict)
    anchor_urban_edge_m: int = 0
    projected_edge_tolerance_degrees: float = 0.0
    boundary_evidence: Evidence = field(default_factory=Evidence)
    boundary_anchor_edge_m: int = 0

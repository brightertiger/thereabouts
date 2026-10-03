"""Schema for source reconciliation and the existing administrative conventions."""

from dataclasses import dataclass, field


@dataclass
class State:
    source: str = ""
    level: str = ""
    reason: str = ""
    include_direct_region_localities: bool = False


@dataclass
class Rollup:
    country: str = ""
    subtype: str = ""
    region_code: str | None = None
    local_name_suffix: str | None = None
    target_wikidata: str = ""
    expected_entities: int = 0
    entity_ids: list[str] = field(default_factory=list)
    members: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    reference: str = ""


@dataclass
class Reconcile:
    version: str = ""
    perspective: str = ""
    offshore_m: int = 0
    nearest_m: int = 0
    name_match_m: int = 0
    wikidata_match_m: int = 0
    minimum_population: int = 0
    pilot: list[str] = field(default_factory=list)
    settlement_codes: list[str] = field(default_factory=list)
    excluded_subtypes: list[str] = field(default_factory=list)
    city_subtypes: list[str] = field(default_factory=list)
    city_states: list[str] = field(default_factory=list)
    no_state: list[str] = field(default_factory=list)
    sovereigns: dict[str, list[str]] = field(default_factory=dict)
    states: dict[str, State] = field(default_factory=dict)
    default_state: State = field(default_factory=State)
    compatible_gb_licenses: list[str] = field(default_factory=list)
    rollups: list[Rollup] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    state_vote_minimum: int = 0
    state_vote_fraction: float = 0.0
    trusted_city_classes: list[str] = field(default_factory=list)
    settlement_classes: list[str] = field(default_factory=list)
    hierarchy_city_classes: list[str] = field(default_factory=list)
    hierarchy_city_minimum: int = 0
    hierarchy_population_ratio: int = 0
    country_reference_codes: list[str] = field(default_factory=list)
    region_city_classes: list[str] = field(default_factory=list)

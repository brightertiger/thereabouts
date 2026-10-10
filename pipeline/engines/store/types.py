"""Typed rows of the country artifact; the packed JSON holds exactly these keys."""

from typing import Any, NotRequired, TypedDict


class Division(TypedDict):
    """An Overture division place, packed into `divisions.data` as normalized."""

    source: str
    source_id: str
    kind: str
    name: str
    name_en: str | None
    latitude: float
    longitude: float
    feature_class: str | None
    feature_code: str | None
    subtype: str | None
    country_code: str | None
    admin1_code: str | None
    admin2_code: str | None
    parent_source_id: str | None
    population: int | None
    source_release: str
    license: str
    provenance: str


class Entity(TypedDict):
    """A canonical identity (`reconcile.entities.make_entity`) in `entities.data`."""

    id: str
    role: str
    name: str | None
    local_name: str | None
    country_code: str
    code: str | None
    code_status: str
    parent: str | None
    population: int | None
    geonames_id: str | None
    geonames_admin1: str | None
    feature_code: str | None
    source_subtype: str | None
    settlement_class: str | None
    source_ids: list[dict[str, str]]
    provenance: list[dict[str, Any]]
    link: dict[str, Any] | None
    name_provenance: dict[str, str | None]
    sovereign: list[str] | None
    # Set by later reconcile steps on some entities only.
    parent_method: NotRequired[str | None]
    city_exclusion: NotRequired[str]
    boundary_status: NotRequired[str]

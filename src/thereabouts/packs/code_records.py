"""Structural contract for portable exact-key candidate payloads."""

from typing import Any

from h3.api import basic_int as h3

from .jsonio import integer, relative_name, string
from .keys import AIRPORT_SCHEMES
from .layout import CITY_METHODS, check_label

METHOD_FIELDS = {"city", "state", "country", "land"}
CANDIDATE_FIELDS = {
    "id",
    "entity",
    "refs",
    "methods",
    "distance",
    "observations",
    "warnings",
}
OBSERVATION_FIELDS = {
    "source",
    "source_id",
    "source_release",
    "license",
    "golden_table",
    "fields",
    "reference",
    "refs",
    "flags",
    "cell_status",
    "country_disagrees",
}


def refs(value: Any, count: int) -> None:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("Expected country, state and city references")
    if any(integer(ref) > count for ref in value):
        raise ValueError("Dangling exact-key catalogue reference")


def methods(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != METHOD_FIELDS:
        raise ValueError("Invalid exact-key methods")
    if (
        value["city"] not in CITY_METHODS
        or value["state"] not in (None, "area")
        or value["country"] not in (None, "area")
        or value["land"] not in ("land", "offshore", "unknown")
    ):
        raise ValueError("Unknown exact-key method")


def observation(value: Any, count: int) -> None:
    if not isinstance(value, dict) or set(value) != OBSERVATION_FIELDS:
        raise ValueError("Invalid observation fields")
    for name in ("source", "source_id", "source_release", "license"):
        string(value[name])
    relative_name(string(value["golden_table"]))
    if not isinstance(value["fields"], dict):
        raise ValueError("Expected original observation fields")
    refs(value["refs"], count)
    check_label((*value["refs"], integer(value["flags"])), count)
    if value["cell_status"] not in ("matched", "unassigned", "ineligible", "unlocated"):
        raise ValueError("Unfinished observation join")
    if (
        value["country_disagrees"] is not None
        and type(value["country_disagrees"]) is not bool
    ):
        raise ValueError("Invalid source-country disagreement")
    reference = value["reference"]
    if reference is None:
        if value["cell_status"] != "unlocated" or any(value["refs"]) or value["flags"]:
            raise ValueError("Missing located observation reference")
        return
    if not isinstance(reference, dict) or set(reference) != {"h3", "stored_h3"}:
        raise ValueError("Invalid observation reference")
    cell = int(string(reference["h3"]), 16)
    if (
        not h3.is_valid_cell(cell)
        or h3.get_resolution(cell) != 8
        or f"{cell:x}" != reference["h3"]
    ):
        raise ValueError("Invalid observation H3 cell")
    stored = reference["stored_h3"]
    if stored is not None:
        number = int(string(stored), 16)
        depth = h3.get_resolution(number)
        if (
            not h3.is_valid_cell(number)
            or not 3 <= depth <= 8
            or h3.cell_to_parent(cell, depth) != number
            or f"{number:x}" != stored
        ):
            raise ValueError("Observation stored cell is not its logical ancestor")
    if (stored is not None) != (value["cell_status"] in ("matched", "unassigned")):
        raise ValueError("Observation reference disagrees with join status")


def payload(value: dict[str, Any], count: int) -> None:
    if set(value) != {"candidates"} or not isinstance(value["candidates"], list):
        raise ValueError("Invalid exact payload")
    previous = b""
    for candidate in value["candidates"]:
        if not isinstance(candidate, dict) or set(candidate) != CANDIDATE_FIELDS:
            raise ValueError("Invalid exact candidate fields")
        identity = string(candidate["id"]).encode("utf-8")
        if identity <= previous:
            raise ValueError("Unsorted or duplicate candidate identity")
        previous = identity
        refs(candidate["refs"], count)
        methods(candidate["methods"])
        entity = candidate["entity"]
        if entity is not None:
            if not isinstance(entity, dict) or set(entity) != {
                "id",
                "name",
                "role",
                "country_code",
                "codes",
                "type",
            }:
                raise ValueError("Invalid source entity")
            if (
                entity["id"] != candidate["id"]
                or entity["role"] != "airport"
                or not isinstance(entity["codes"], dict)
            ):
                raise ValueError("Invalid airport identity")
            if set(entity["codes"]) != set(AIRPORT_SCHEMES) or any(
                code is not None and not isinstance(code, str)
                for code in entity["codes"].values()
            ):
                raise ValueError("Invalid airport code fields")
            for field in ("name", "country_code", "type"):
                if entity[field] is not None and not isinstance(entity[field], str):
                    raise ValueError("Invalid source entity text")
        distance = candidate["distance"]
        if distance is not None:
            if not isinstance(distance, dict) or set(distance) != {
                "greater_than_m",
                "at_most_m",
                "cutoff_m",
                "exact_m",
            }:
                raise ValueError("Invalid distance band")
            upper, cutoff = (
                integer(distance["at_most_m"], 1),
                integer(distance["cutoff_m"], 1),
            )
            lower = distance["greater_than_m"]
            if (
                upper > cutoff
                or (lower is not None and integer(lower) >= upper)
                or distance["exact_m"] is not None
            ):
                raise ValueError("Invalid distance bounds")
        if not isinstance(candidate["warnings"], list) or any(
            not isinstance(w, str) or not w for w in candidate["warnings"]
        ):
            raise ValueError("Invalid warning codes")
        if (
            not isinstance(candidate["observations"], list)
            or not candidate["observations"]
        ):
            raise ValueError("Candidate lacks observations")
        for row in candidate["observations"]:
            observation(row, count)

"""One settlement-agreement definition shared by scalar and stored-cell checks."""

from __future__ import annotations

from collections import Counter

from pipeline.engines.store.codec import Row


def compare(
    place: Row,
    country: str,
    country_id: str | None,
    city_geonames_id: str | None,
    city_present: bool,
    city_method: str | None,
    state_code: str | None,
    policy: Row,
) -> tuple[Counter[str], Row]:
    country_ok = country_id == f"country:{country}"
    applicable = country not in policy["no_state"] and bool(place["admin1_code"])
    state_ok = applicable and state_code == place["admin1_code"]
    same = bool(city_geonames_id and city_geonames_id == place["source_id"])
    containing = city_present and country_ok and city_method == "area"
    values = {
        "answer": bool(country_id),
        "country_agrees": country_ok,
        "state_applicable": applicable,
        "state_agrees": state_ok,
        "state_unmapped": applicable and state_code is None,
        "city_present": city_present,
        "city_same_identity": same,
        "city_containing_other": containing and not same,
        "city_same_or_containing": same or containing,
    }
    return Counter({k: int(v) for k, v in values.items()}), {
        "country_ok": country_ok,
        "state_ok": not applicable or state_ok,
        "city_ok": same or containing,
        "city_same_identity": same,
    }

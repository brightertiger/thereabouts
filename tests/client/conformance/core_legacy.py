"""Explicit migration assertions against the unchanged legacy fixture."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from thereabouts import Geocoder, Result

FIXTURES = Path(__file__).parents[2] / "fixtures"
MISS_REASONS = {
    "unassigned": "unassigned",
    "ineligible": "no_land",
    "outside_coverage": "outside_coverage",
}
# These are the only intended differences in existing fields.
COARSE_CELL_CASE = 47
CANONICAL_NAMES = {
    "city:synthetic:A": ("München 東京 city:synthetic:A", "München 東京")
}


def resolve(geo: Geocoder, case: dict[str, Any]) -> Result:
    request = case["request"]
    values = request["values"]
    return (
        geo.from_h3(values[0], evidence=True)
        if request["kind"] == "h3"
        else geo.reverse(lat=values[0], lon=values[1], evidence=True)
    )


def assert_case(geo: Geocoder, case: dict[str, Any]) -> str:
    """Compare old meanings, rather than comparing two newly generated snapshots."""
    result = resolve(geo, case)
    if case["id"] == COARSE_CELL_CASE:
        assert case["request"] == {"kind": "h3", "values": ["836014fffffffff"]}
        assert case["error"]["name"] == "InvalidInputError"
        assert result.status == "not_found"
        assert result.evidence is not None
        assert result.evidence.reason == "no_stored_ancestor"
        return "coarse_cell_intended_change"
    if "error" in case:
        assert case["error"]["name"] == "InvalidInputError"
        assert result.status == "invalid_input"
        return "invalid_input"
    previous = case["result"]
    if previous["status"] != "matched":
        assert result.status == "not_found"
        assert result.evidence is not None
        assert result.evidence.reason == MISS_REASONS[previous["status"]]
        assert result.country is None and result.state is None and result.city is None
        return str(previous["status"])
    selected = previous["selected"]
    assert result.status == "matched" and result.evidence is not None
    for field in ("country", "state", "city"):
        old = selected[field]
        new = getattr(result, field)
        assert getattr(result.evidence, f"{field}_id") == (old["id"] if old else None)
        if old is None:
            assert new is None
            continue
        assert new is not None
        if field == "country":
            assert new.code == old["country_code"]
        if field == "city":
            assert new.id == old["id"]
        if field == "city" and old["id"] in CANONICAL_NAMES:
            assert (old["name"], new.name) == CANONICAL_NAMES[old["id"]]
        else:
            assert new.name == old["name"]
    method = selected["methods"]["city"]
    assert result.match == {
        "rural_nearest": "nearest",
        "rural_nearest_distant": "nearest_distant",
    }.get(method, "contained")
    assert result.evidence.city_method == method
    assert result.evidence.land_method == selected["methods"]["land"]
    return "matched"


def check() -> dict[str, int]:
    counts: Counter[str] = Counter()
    cases = json.loads((FIXTURES / "conformance.json").read_text())["cases"]
    with Geocoder(FIXTURES / "packs/core-synthetic") as geo:
        for case in cases:
            if case["request"]["kind"] in {"h3", "coordinates"}:
                counts[assert_case(geo, case)] += 1
    assert sum(counts.values()) == 35
    return dict(counts)

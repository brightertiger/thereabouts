"""Assert original code expectations with explicit migration allowances."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from thereabouts import Geocoder, Result

FIXTURES = Path(__file__).parents[1] / "fixtures"


def resolve(
    geo: Geocoder, request: dict[str, Any], *, evidence: bool = False
) -> Result:
    if request["kind"] == "geocode":
        kwargs = {k: v for k, v in request.items() if k not in {"kind", "values"}}
        return geo.geocode(request["values"][0], evidence=evidence, **kwargs)
    if request["kind"] == "plate":
        return geo.plate(
            request["values"][0],
            country=request.get("country"),
            series=request.get("series"),
            evidence=evidence,
        )
    if request["kind"] == "ip":
        return geo.ip(request["values"][0], evidence=evidence)
    if request["kind"] == "phone":
        return geo.phone(request["values"][0], evidence=evidence)
    if request["kind"] == "locode":
        return geo.locode(
            request["values"][0], country=request.get("country"), evidence=evidence
        )
    if request["kind"] == "airport":
        return geo.airport(
            request["values"][0],
            scheme=request.get("scheme"),
            country=request.get("country"),
            evidence=evidence,
        )
    return geo.postal(
        request["values"][0], country=request.get("country"), evidence=evidence
    )


def assert_case(geo: Geocoder, case: dict[str, Any]) -> str:
    result = resolve(geo, case["request"], evidence=True)
    if case["id"] == 52:
        # Approved default now searches IATA + ICAO; assert against case 32's
        # unchanged airport expectations, not against a regenerated snapshot.
        original = json.loads((FIXTURES / "conformance.json").read_text())
        expected = next(c["result"] for c in original["cases"] if c["id"] == 32)
        case = {"id": 52, "request": case["request"], "result": expected}
    if "error" in case:
        assert case["error"]["name"] in {"ContextRequiredError", "InvalidInputError"}
        assert result.status == "invalid_input" and result.hint is not None
        return "invalid_input"
    old = case["result"]
    assert result.status == old["status"]
    answers = result.candidates if result.status == "ambiguous" else (result,)
    if result.status == "not_found":
        assert all(v is None for v in (result.country, result.state, result.city))
        return "not_found"
    assert len(answers) == len(old["candidates"])
    candidates = {c["id"]: c for c in old["candidates"]}
    for answer in answers:
        assert answer.match == "exact"
        assert answer.evidence is not None
        sources = [dict(s) for s in answer.evidence.source_ids or ()]
        identity = (
            answer.city.id
            if answer.city and case["request"]["kind"] == "postal"
            else (
                f"{case['request']['kind']}:"
                f"{sources[0]['source']}:{sources[0]['source_id']}"
            )
        )
        previous = candidates[identity]
        # Legacy candidates store the published source point in observations.
        anchor = sorted(
            previous["observations"],
            key=lambda o: (
                o["source"],
                o["source_id"],
                o["fields"].get("name") or o["fields"].get("place_name") or "",
            ),
        )[0]["fields"]
        if anchor["latitude"] is None:
            assert anchor["longitude"] is None and answer.point is None
        else:
            assert answer.point is not None
            assert answer.point.lat == pytest.approx(
                anchor["latitude"], abs=0.00000051, rel=0
            )
            assert answer.point.lon == pytest.approx(
                anchor["longitude"], abs=0.00000051, rel=0
            )
        for field in ("country", "state", "city"):
            before = previous[field]
            after = getattr(answer, field)
            assert getattr(answer.evidence, f"{field}_id") == (
                before["id"] if before else None
            )
            if case["id"] == 29 and field == "country":
                # Approved F6: original unlinked source retains null evidence ID,
                # while its public country now comes from the AA key.
                assert before is None and after is not None and after.code == "AA"
                assert answer.evidence.reason == "country_from_key"
            elif before is None:
                assert after is None
            else:
                assert after is not None
                if field == "city" and before["id"] == "city:synthetic:A":
                    # Same canonical-name allowance as the reverse migration.
                    assert before["name"] == "München 東京 city:synthetic:A"
                    assert after.name == "München 東京"
                else:
                    assert after.name == before["name"]
                if field == "country":
                    assert after.code == before["country_code"]
        assert {(s["source"], s["source_id"]) for s in sources} == {
            (o["source"], o["source_id"]) for o in previous["observations"]
        }
    if result.status == "ambiguous":
        # Approved consensus change: candidates still assert legacy expectations;
        # only their agreed flat fields now propagate to the ambiguous result.
        for field in ("country", "state", "city", "point", "timezone", "cell", "match"):
            first = getattr(answers[0], field)
            common = first if all(getattr(a, field) == first for a in answers) else None
            assert getattr(result, field) == common
    return str(result.status)


def check(family: str = "postal") -> dict[str, int]:
    counts: Counter[str] = Counter()
    with Geocoder(FIXTURES / f"packs/{family}-synthetic") as geo:
        for case in json.loads((FIXTURES / "conformance.json").read_text())["cases"]:
            if case["request"]["kind"] == (
                "airport" if family == "airports" else family
            ):
                counts[assert_case(geo, case)] += 1
    return dict(counts)

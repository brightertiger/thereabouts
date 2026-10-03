"""Assert original code expectations with explicit migration allowances."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from thereabouts import Geocoder, Result

FIXTURES = Path(__file__).parents[1] / "fixtures"


def resolve(
    geo: Geocoder, request: dict[str, Any], *, evidence: bool = False
) -> Result:
    return geo.postal(
        request["values"][0], country=request.get("country"), evidence=evidence
    )


def assert_case(geo: Geocoder, case: dict[str, Any]) -> str:
    result = resolve(geo, case["request"], evidence=True)
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
            if answer.city
            else f"postal:{sources[0]['source']}:{sources[0]['source_id']}"
        )
        previous = candidates[identity]
        for field in ("country", "state", "city"):
            before = previous[field]
            after = getattr(answer, field)
            assert getattr(answer.evidence, f"{field}_id") == (
                before["id"] if before else None
            )
            if before is None:
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
        assert all(
            v is None for v in (result.country, result.state, result.city, result.point)
        )
    return str(result.status)


def check(family: str = "postal") -> dict[str, int]:
    counts: Counter[str] = Counter()
    with Geocoder(FIXTURES / f"packs/{family}-synthetic") as geo:
        for case in json.loads((FIXTURES / "conformance.json").read_text())["cases"]:
            if case["request"]["kind"] == family:
                counts[assert_case(geo, case)] += 1
    return dict(counts)

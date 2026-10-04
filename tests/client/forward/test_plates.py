"""Compare plate matches and geographic eligibility with the independent reference."""

import copy
import json
from pathlib import Path

import pytest

from pipeline.engines.plate_country.resolver import Resolver
from tests.client.conformance.pack_selection import selection
from tests.tools.source_fixture import read_source
from thereabouts import Geocoder

FIXTURES = Path(__file__).parents[2] / "fixtures"


def test_plate_vectors() -> None:
    bundle = json.loads((FIXTURES / "plates-vectors.json").read_text())
    with Geocoder(packs=selection(FIXTURES / bundle["pack"])) as geo:
        for case in bundle["cases"]:
            r = case["request"]
            assert (
                geo.plate(
                    r["values"][0], country=r.get("country"), series=r.get("series")
                ).to_dict()
                == case["result"]
            ), case["id"]


def test_reference_plate_matches() -> None:
    source = read_source(FIXTURES / "plates-source.json.gz")
    reference = copy.deepcopy(source["bundle"])
    # Missing vehicle priors are an explicit sample omission. Disable this term
    # in the independent reference; the neutral row only satisfies its constructor.
    if not reference["priors"]:
        reference["policy"]["weights"]["log_vehicle_prior"] = 0
        reference["priors"] = [{"country_code": "US", "vehicles": 1}]
    resolver = Resolver(reference)
    vectors = json.loads((FIXTURES / "plates-vectors.json").read_text())
    with Geocoder(packs=selection(FIXTURES / "packs/plates-sample")) as geo:
        for case in vectors["cases"]:
            r = case["request"]
            if r.get("country") == "ZZ":
                continue
            old = resolver.resolve(
                r["values"][0], r.get("country"), series=r.get("series")
            )
            result = geo.plate(
                r["values"][0],
                country=r.get("country"),
                series=r.get("series"),
                evidence=True,
            )
            if r.get("country"):
                assert result.country is not None
                assert result.country.code == old["country_code"]
                assert result.status == "matched" and result.match == "exact"
                assert result.evidence is not None
                assert result.evidence.reason == old["reason"]
                if old["level"] == "state" and not old.get("ambiguous"):
                    assert result.state is not None
                    assert result.state.name in {
                        s.get("name_en") or s.get("name_local")
                        for s in old["locations"]
                    }
                else:
                    assert result.state is None
                compare_rules(result.evidence.source_ids or (), old.get("matches", []))
            else:
                candidates = old["candidates"]
                if r["values"][0].strip().upper() == "UNKNOWN":
                    # Approved missing-serial handling overrides the old broad US rule.
                    assert result.status == "not_found" and result.country is None
                    continue
                expected = (
                    "matched"
                    if len(candidates) == 1
                    else ("ambiguous" if candidates else "not_found")
                )
                assert result.status == expected
                answers = (result,) if len(candidates) == 1 else result.candidates
                assert [c.country.code for c in answers if c.country] == [
                    c["country_code"] for c in candidates
                ]
                for answer, candidate in zip(answers, candidates, strict=True):
                    assert answer.evidence is not None
                    compare_rules(
                        answer.evidence.source_ids or (), candidate["evidence"]
                    )


def compare_rules(
    sources: tuple[tuple[tuple[str, str], ...], ...], matches: list[dict[str, object]]
) -> None:
    actual = [dict(s) for s in sources if dict(s).get("source") == "plate_format"]
    assert len(actual) == len(matches)
    previous = {str(m["series_id"]): m for m in matches}
    for observation in actual:
        old = previous[observation["source_id"]]
        assert observation.get("code") == old["code"]
        assert float(observation["score"]) == pytest.approx(old["score"], abs=0.0000011)
        assert observation["match"] == old["match"]


def test_plate_columns_keep_supplied_country() -> None:
    with Geocoder(packs=selection(FIXTURES / "packs/plates-sample")) as geo:
        values = ["ABC 123", "", "unknown", "1A 12345"]
        columns = geo.plate_columns(values, country="US")
        assert (
            columns["country_code_categories"][columns["country_code"]].tolist()
            == ["US"] * 4
        )
        assert (
            columns["status_categories"][columns["status"]].tolist() == ["matched"] * 4
        )

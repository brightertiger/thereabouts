"""Longest prefixes, independent phone sources and country ambiguity."""

import json
from pathlib import Path

import pytest

from tests.conformance.pack_selection import selection
from thereabouts import Geocoder
from tools.source_fixture import read_source

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.mark.parametrize("name", ["phone-vectors.json", "phone-synthetic-vectors.json"])
def test_phone_vectors(name: str) -> None:
    bundle = json.loads((FIXTURES / name).read_text())
    with Geocoder(packs=selection(FIXTURES / bundle["pack"])) as geo:
        for case in bundle["cases"]:
            assert (
                geo.phone(case["request"]["values"][0]).to_dict() == case["result"]
            ), case["id"]


def test_independent_phone_prefixes() -> None:
    rows = read_source(FIXTURES / "phone-source.json.gz")["rows"]
    with Geocoder(packs=selection(FIXTURES / "packs/phone-sample")) as geo:
        for row in rows:
            prefix = row["prefix"] or row["calling_code"]
            result = geo.phone("+" + prefix, evidence=True)
            answers = result.candidates if result.status == "ambiguous" else (result,)
            assert {a.country.code for a in answers if a.country} == {
                c
                for r in rows
                if (r["prefix"] or r["calling_code"]) == prefix
                for c in r["country_codes"]
            }
            assert all(a.kind == "phone_prefix" and a.match == "exact" for a in answers)
            observations = [
                dict(s)
                for a in answers
                if a.evidence
                for s in a.evidence.source_ids or ()
            ]
            assert (row["source"], row["source_id"]) in {
                (s["source"], s["source_id"]) for s in observations
            }
            # The extract has country links; description is not a city link.
            if row["place_id"] == row["country_id"]:
                assert all(a.city is None and a.state is None for a in answers)


def test_nested_prefix_and_shared_calling_code() -> None:
    with Geocoder(packs=selection(FIXTURES / "packs/phone-synthetic")) as geo:
        ambiguous = geo.phone("+1")
        assert ambiguous.status == "ambiguous"
        assert ambiguous.country is None and ambiguous.point is None
        assert {c.country.code for c in ambiguous.candidates if c.country} == {
            "AA",
            "BB",
        }
        city = geo.phone("+1 (202) 555-1234")
        assert city.country is not None and city.country.code == "AA"
        assert city.city is not None and city.city.id == "city:synthetic:A"
        assert city.state is not None
        less_specific = geo.phone("+1209")
        assert less_specific.country is not None
        assert less_specific.country.code == "BB"
        columns = geo.phone_columns(["+1", "+1202", "+1209", "bad", "+44"])
        assert columns["status_categories"][columns["status"]].tolist() == [
            "ambiguous",
            "matched",
            "matched",
            "invalid_input",
            "not_found",
        ]
        assert columns["candidate_offsets"].tolist() == [0, 2, 2, 2, 2, 2]

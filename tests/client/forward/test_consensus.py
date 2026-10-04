"""Ambiguity retains shared context, including candidates hidden by a display limit."""

import json
from pathlib import Path

import pytest

from tests.client.conformance.forward_legacy import resolve
from tests.client.conformance.pack_selection import selection
from thereabouts import Geocoder

FIXTURES = Path(__file__).parents[2] / "fixtures"
FIELDS = (
    "country",
    "state",
    "city",
    "timezone",
    "point",
    "cell",
    "match",
    "distance_band",
)


@pytest.mark.parametrize(
    "family", ["postal", "airports", "locode", "phone", "plates", "geocode"]
)
def test_flat_fields_are_the_consensus_of_all_candidates(family: str) -> None:
    bundle = json.loads((FIXTURES / f"{family}-vectors.json").read_text())
    with Geocoder(packs=selection(FIXTURES / bundle["pack"])) as geo:
        for case in bundle["cases"]:
            request = case["request"]
            result = resolve(geo, request)
            if result.status != "ambiguous":
                continue
            all_answers = (
                resolve(geo, request | {"limit": 100}).candidates
                if family == "geocode"
                else result.candidates
            )
            for field in FIELDS:
                first = getattr(all_answers[0], field)
                common = (
                    first
                    if all(getattr(c, field) == first for c in all_answers)
                    else None
                )
                assert getattr(result, field) == common, (case["id"], field)


def test_unlinked_postal_candidates_inherit_only_source_country() -> None:
    with Geocoder(packs=selection(FIXTURES / "packs/postal-sample")) as geo:
        result = geo.postal("744301", country="IN", evidence=True)
        assert result.status == "ambiguous"
        assert result.country is not None and result.country.code == "IN"
        missing = [
            c for c in result.candidates if c.evidence and c.evidence.country_id is None
        ]
        assert missing
        for candidate in missing:
            assert candidate.country == result.country
            assert candidate.state is None and candidate.city is None
            assert candidate.evidence is not None
            assert candidate.evidence.reason == "country_from_key"


def test_single_plate_inference_and_unknown_placeholder() -> None:
    with Geocoder(packs=selection(FIXTURES / "packs/plates-sample")) as geo:
        result = geo.plate("AB-123-CD", evidence=True)
        assert result.status == "matched" and not result.candidates
        assert result.country is not None and result.country.code == "FR"
        assert result.rank_basis == "plate_evidence_without_vehicle_prior"
        assert result.evidence is not None
        assert result.evidence.reason == "plate_country_inferred"
        assert geo.plate(" unknown ").status == "not_found"
        hinted = geo.plate("unknown", country="US")
        assert hinted.status == "matched" and hinted.country is not None
        assert hinted.country.code == "US"

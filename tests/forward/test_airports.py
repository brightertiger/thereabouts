"""Airports preserve source identity across schemes and explicit legacy expectations."""

import json
from pathlib import Path

import pytest

from tests.conformance.forward_legacy import check, resolve
from thereabouts import Geocoder

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.mark.parametrize(
    "name", ["airports-vectors.json", "airports-synthetic-vectors.json"]
)
def test_airport_vectors(name: str) -> None:
    bundle = json.loads((FIXTURES / name).read_text())
    with Geocoder(FIXTURES / bundle["pack"]) as geo:
        for case in bundle["cases"]:
            assert resolve(geo, case["request"]).to_dict() == case["result"], case["id"]


def test_airport_legacy_expectations() -> None:
    assert check("airports") == {
        "ambiguous": 2,
        "matched": 7,
        "not_found": 1,
        "invalid_input": 1,
    }


def test_independent_airport_sources() -> None:
    oracle = json.loads((FIXTURES / "airports-source.json").read_text())
    with Geocoder(FIXTURES / "packs/airports-sample") as geo:
        for row in oracle["rows"]:
            for scheme, field in [
                ("iata", "iata_code"),
                ("icao", "icao_code"),
                ("gps", "gps_code"),
                ("local", "local_code"),
                ("ident", "ident"),
            ]:
                if not row[field]:
                    continue
                result = geo.airport(
                    row[field],
                    scheme=scheme,
                    country=row["country_code"],
                    evidence=True,
                )
                answers = (
                    result.candidates if result.status == "ambiguous" else (result,)
                )
                matches = [
                    a
                    for a in answers
                    if a.evidence
                    and any(
                        dict(s).get("source_id") == row["source_id"]
                        for s in a.evidence.source_ids or ()
                    )
                ]
                assert len(matches) == 1
                answer = matches[0]
                assert answer.evidence is not None
                assert answer.evidence.city_id == (
                    oracle["place_to_city"].get(row["city_id"]) or row["city_id"]
                )
                assert answer.evidence.country_id == row["country_id"]
                assert row["name"] in [
                    dict(s).get("name") for s in answer.evidence.source_ids or ()
                ]
                if row["latitude"] is not None:
                    assert answer.point is not None
                    assert answer.point.lat == pytest.approx(
                        row["latitude"], abs=0.00000051
                    )
                    assert answer.point.lon == pytest.approx(
                        row["longitude"], abs=0.00000051
                    )


def test_airport_columns_candidates() -> None:
    with Geocoder(FIXTURES / "packs/airports-synthetic") as geo:
        result = geo.airport_columns(["ZZZ", "AAAA", "bad"])
        assert result["status_categories"][result["status"]].tolist() == [
            "ambiguous",
            "matched",
            "not_found",
        ]
        assert result["candidate_offsets"].tolist() == [0, 2, 2, 2]


def test_duplicate_identity_names_follow_the_published_scheme() -> None:
    with Geocoder(FIXTURES / "packs/airports-synthetic") as geo:
        iata = geo.airport("ZZZ", scheme="iata", country="AA", evidence=True)
        gps = geo.airport("GPS1", scheme="gps", evidence=True)
    assert iata.evidence is not None and gps.evidence is not None
    assert {dict(s)["name"] for s in iata.evidence.source_ids or ()} == {
        "First airport",
        "First airport renamed",
    }
    assert {dict(s)["name"] for s in gps.evidence.source_ids or ()} == {"First airport"}

"""Name vectors and independent checks of source geography and ambiguity."""

import json
from pathlib import Path

import pytest

from tests.conformance.forward_legacy import resolve
from thereabouts import Geocoder
from tools.source_fixture import read_source

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.mark.parametrize(
    "name", ["geocode-vectors.json", "geocode-synthetic-vectors.json"]
)
def test_geocode_vectors(name: str) -> None:
    bundle = json.loads((FIXTURES / name).read_text())
    with Geocoder(FIXTURES / bundle["pack"]) as geo:
        for case in bundle["cases"]:
            assert resolve(geo, case["request"]).to_dict() == case["result"], case["id"]


def test_independent_city_rows_and_population_ranking() -> None:
    rows = read_source(FIXTURES / "geocode-source.json.gz")["rows"]
    with Geocoder(FIXTURES / "packs/core-names-sample") as geo:
        for row in rows:
            result = geo.geocode(row["name"], country=row["country_code"], limit=100)
            answers = result.candidates if result.status == "ambiguous" else (result,)
            matches = [a for a in answers if a.city and a.city.id == row["city_id"]]
            assert len(matches) == 1
            answer = matches[0]
            assert (
                answer.country is not None
                and answer.country.code == row["country_code"]
            )
            assert answer.city is not None and answer.city.name == row["name"]
            assert answer.city.population == (row["population"] or None)
            assert answer.rank_basis == "population" and answer.match == "exact"
            assert answer.point is not None
            assert answer.point.lat == pytest.approx(row["latitude"], abs=0.00000051)
            assert answer.point.lon == pytest.approx(row["longitude"], abs=0.00000051)
        springfields = sorted(
            [r for r in rows if r["name"] == "Springfield"],
            key=lambda r: (-(r["population"] or 0), r["city_id"]),
        )
        ambiguous = geo.geocode("Springfield", limit=100)
        assert ambiguous.status == "ambiguous"
        assert ambiguous.city is None
        assert ambiguous.country is not None and ambiguous.country.code == "US"
        limited = geo.geocode("Springfield", limit=1)
        assert limited.state == ambiguous.state and limited.point == ambiguous.point
        assert limited.country == ambiguous.country and limited.cell == ambiguous.cell
        assert [c.city.id for c in ambiguous.candidates if c.city] == [
            r["city_id"] for r in springfields
        ]
        assert len(geo.geocode("Springfield", limit=1).candidates) == 1
        assert geo.geocode("Springfield", limit=1).status == "ambiguous"
        preferred = geo.geocode("Springfield", prefer="population")
        assert preferred.status == "matched" and preferred.city is not None
        assert preferred.city.id == springfields[0]["city_id"]
        illinois = geo.geocode("Springfield", country="US", subdivision="US-IL")
        assert illinois.status == "matched" and illinois.state is not None
        assert illinois.state.code == "US-IL"


def test_english_and_future_alternate_table() -> None:
    with Geocoder(FIXTURES / "packs/core-names-synthetic") as geo:
        for name in ["Munich Tokyo", "Minga Tokyo"]:
            result = geo.geocode(name)
            assert result.status == "matched" and result.match == "alternate_name"
            assert result.city is not None and result.city.name == "München 東京"
        assert geo.geocode("munchen 東京").match == "exact"
        assert geo.geocode("Ming Tokyo").match == "fuzzy"


def test_name_batch_filters_and_invalid_limit() -> None:
    values = ["Springfield", "Pariss", "75001", "12 Main Street"]
    with Geocoder(FIXTURES / "packs/core-names-sample") as geo:
        columns = geo.geocode_columns(values, country="US", limit=3)
        assert columns["status_categories"][columns["status"]].tolist() == [
            geo.geocode(v, country="US", limit=3).status for v in values
        ]
        assert columns["candidate_offsets"][1] == 3
        assert geo.geocode("Paris", limit=10**100).status == "invalid_input"
        assert geo.geocode("Springfield", country="FR").status == "not_found"
        assert geo.geocode("Mumbai", subdivision="FR-IDF").status == "not_found"


def test_real_english_name_is_an_alternate_exact_key() -> None:
    rows = read_source(FIXTURES / "geocode-source.json.gz")["rows"]
    row = next(r for r in rows if r["city_id"] == "city:geonames:11189062")
    assert row["name"] == "Kidarakulam" and row["name_en"] == "Karakulam"
    with Geocoder(FIXTURES / "packs/core-names-sample") as geo:
        result = geo.geocode(row["name_en"], country=row["country_code"])
        assert result.status == "matched" and result.match == "alternate_name"
        assert result.city is not None and result.city.id == row["city_id"]
        assert result.city.name == row["name"]

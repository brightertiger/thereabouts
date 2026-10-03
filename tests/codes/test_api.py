from pathlib import Path

import pytest

from thereabouts.client import Geocoder
from thereabouts.client_errors import (
    AmbiguousResultError,
    ContextRequiredError,
    InvalidInputError,
)
from thereabouts.errors import ClosedGeocoderError, DataNotInstalledError
from thereabouts.results import SourcePlace


def test_postal_preserves_leading_zeros_editions_and_ambiguity(
    code_packs: dict[str, Path],
) -> None:
    with Geocoder(code_packs["postal"]) as geo:
        answer = geo.postal("00100", country=" aa ")
        selected = answer.require_one()
        assert (
            selected is not None
            and selected.city
            and selected.city.id == "city:synthetic:A"
        )
        assert selected.place is None and selected.id == selected.city.id
        assert [row.fields["variant"] for row in selected.observations] == [
            "base",
            "full",
        ]
        assert all(
            row.reference and row.methods.city == "city_polygon"
            for row in selected.observations
        )
        assert geo.postal("100", country="AA").status == "not_found"
        ambiguous = geo.postal("AMB", country="AA")
        assert ambiguous.status == "ambiguous" and ambiguous.selected is None
        assert [item.id for item in ambiguous.candidates] == [
            "city:synthetic:A",
            "city:synthetic:unused",
        ]
        with pytest.raises(AmbiguousResultError):
            ambiguous.require_one()
        with pytest.raises(ContextRequiredError):
            geo.postal("00100")
        with pytest.raises(InvalidInputError):
            geo.postal(100, country="AA")  # type: ignore[arg-type]
        assert geo.postal("a1a1a1", country="ca").status == "matched"
        assert geo.postal("A1A 1A1", country="CA").query.value == "A1A1A1"
        with pytest.raises(DataNotInstalledError):
            geo.reverse(0, 0)
    assert answer.to_dict()["selected"]["id"] == selected.id
    with pytest.raises(ClosedGeocoderError):
        geo.postal("00100", country="AA")


def test_source_coordinate_disagreement_is_preserved(
    code_packs: dict[str, Path],
) -> None:
    with Geocoder(code_packs["postal"]) as geo:
        answer = geo.postal("560001", country="IN")
        selected = answer.require_one()
        assert (
            selected and selected.city and selected.city.id == "city:synthetic:unused"
        )
        assert (
            selected.observations[0].fields["place_name"] == "Conflicting source label"
        )
        assert selected.observations[0].country_disagrees is True
        assert selected.methods.city == "rural_nearest_distant"
        assert selected.distance and selected.distance.greater_than_m == 25000
        assert {warning.code for warning in answer.warnings} == {
            "source_country_disagrees",
            "distant_nearest",
        }
        unlocated = geo.postal("VOID", country="AA").require_one()
        assert unlocated and unlocated.city is None and unlocated.country is None
        assert unlocated.observations[0].reference is None
        assert unlocated.observations[0].methods.land == "unknown"


def test_airport_schemes_collisions_and_unlocated_closed_sites(
    code_packs: dict[str, Path],
) -> None:
    with Geocoder(code_packs["airports"]) as geo:
        answer = geo.airport(" zzz ", scheme="iata")
        assert answer.status == "ambiguous" and len(answer.candidates) == 2
        assert answer.selected is None
        first = geo.airport("ZZZ", scheme="iata", country="AA").require_one()
        assert first and first.place and first.place.id == "airport:synthetic:a1"
        assert first.place.name is None and len(first.observations) == 2
        assert first.city and first.city.id == "city:synthetic:A"
        closed = geo.airport("L1", scheme="local", country="BB").require_one()
        assert (
            closed
            and isinstance(closed.place, SourcePlace)
            and closed.place.type == "closed"
        )
        assert closed.city is None and closed.observations[0].reference is None
        for code, scheme in (
            ("AA01", "ident"),
            ("AAAA", "icao"),
            ("GPS1", "gps"),
            ("L1", "local"),
        ):
            assert geo.airport(code, scheme=scheme, country="AA").require_one()
        with pytest.raises(ContextRequiredError):
            geo.airport("ZZZ")
        with pytest.raises(ContextRequiredError):
            geo.airport("L1", scheme="local")
        with pytest.raises(InvalidInputError):
            geo.airport("ZZZ", scheme="guess")
        assert geo.airport("ZZZ", scheme="icao").status == "not_found"
        assert geo.info()["packs"]["airports"]["unindexed_rows"] == 1


def test_code_candidates_share_bounded_cache_and_remain_detached(
    code_packs: dict[str, Path],
) -> None:
    with Geocoder(code_packs["postal"], cache_bytes=0) as reference:
        expected = reference.postal("AMB", country="AA")
    with Geocoder(code_packs["postal"]) as geo:
        first = geo.postal("AMB", country="AA")
        before = geo.info()["cache"]["postal"]
        second = geo.postal("AMB", country="AA")
        after = geo.info()["cache"]["postal"]
        assert first == second == expected
        assert first.candidates is second.candidates
        assert (
            after["misses"] == before["misses"] and after["hits"] == before["hits"] + 1
        )
        assert after["retained_bytes"] <= after["budget_bytes"]
    assert second.to_dict() == expected.to_dict()
    with Geocoder(code_packs["postal"], cache_bytes=1024) as tiny:
        assert tiny.postal("AMB", country="AA") == expected
        assert tiny.info()["cache"]["postal"]["evictions"] > 0
        assert tiny.info()["cache"]["postal"]["retained_bytes"] <= 1024

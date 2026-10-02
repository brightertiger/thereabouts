from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from h3.api import basic_int as h3

from thereabouts.client import Geocoder
from thereabouts.client_errors import AmbiguousResultError, InvalidInputError
from thereabouts.results import Place

PACK = Path(__file__).parents[1] / "fixtures/serving"
ROOT = int(h3.latlng_to_cell(12.97, 77.59, 3))
BRANCHES = h3.cell_to_children(ROOT, 4)


def finest(cell: int) -> str:
    return str(h3.int_to_str(h3.cell_to_center_child(cell, 8)))


@pytest.mark.parametrize(
    ("index", "method", "basis"),
    [
        (0, "city_polygon", "source_boundary"),
        (1, "policy_polygon", "policy_boundary"),
        (2, "urban_allocation", "inferred_urban"),
        (3, "town_radius", "inferred_extent"),
        (4, "rural_polygon", "source_boundary"),
        (5, "rural_nearest", "nearest_settlement"),
        (6, "rural_nearest_distant", "nearest_settlement"),
    ],
)
def test_methods(index: int, method: str, basis: str) -> None:
    cell = h3.cell_to_children(BRANCHES[0], 5)[index]
    with Geocoder(PACK, verify=True) as geo:
        answer = geo.from_h3(finest(cell))
    selected = answer.require_one()
    assert answer.status == "matched" and selected is not None
    assert selected.methods.city == method
    assert selected.confidence.basis == basis
    assert selected.confidence.calibrated_probability is None
    assert selected.methods.country == selected.methods.state == "area"
    assert selected.methods.land == ("offshore" if index == 1 else "land")
    assert answer.reference is not None and answer.reference.stored_resolution == 5
    assert answer.reference.stored_h3 == h3.int_to_str(cell)
    assert selected.city is not None and selected.country is not None
    assert selected.city.id == "city:synthetic:A"
    assert selected.city.parent_id == "district:synthetic:A"
    assert selected.city.normalized_city_id == selected.city.id
    assert selected.city.settlement_kind == "city"
    assert selected.city.name_en is None and selected.city.local_name == "東京"
    source_ids = selected.city.evidence.source_ids
    assert isinstance(source_ids, tuple) and isinstance(source_ids[0], Mapping)
    assert source_ids[0]["source"] == "synthetic"
    assert selected.sovereign is not None and selected.sovereign.id == "country:BB"
    assert answer.data.sources[0].release == "fixture"
    if index >= 5:
        assert selected.distance is not None
        assert selected.distance.exact_m is None
        assert selected.distance.at_most_m == (50000 if index == 6 else 25000)
        assert selected.distance.greater_than_m == (25000 if index == 6 else None)
    else:
        assert selected.distance is None
    assert [w.code for w in answer.warnings] == (
        ["distant_nearest"]
        if index == 6
        else ["inferred_extent"]
        if index in (2, 3)
        else []
    )


def test_missing_and_partial_answers() -> None:
    with Geocoder(PACK) as geo:
        unassigned = geo.from_h3(finest(BRANCHES[1]))
        partial = geo.from_h3(finest(BRANCHES[2]))
        ineligible = geo.from_h3(finest(BRANCHES[6]))
        ocean = geo.reverse(0, 179.99)
        outside = geo.reverse(52.37, 4.9)
    assert unassigned.status == "unassigned" and unassigned.selected is None
    assert (
        unassigned.reference is not None and unassigned.reference.stored_resolution == 4
    )
    assert partial.status == "matched" and partial.selected is not None
    assert partial.selected.city is None and partial.selected.methods.city is None
    assert partial.selected.country is not None
    assert ineligible.status == ocean.status == "ineligible"
    assert outside.status == "outside_coverage"
    assert outside.require_one() is None and outside.candidates == ()


def test_immutable_detached_result() -> None:
    geo = Geocoder(PACK)
    answer = geo.from_h3(finest(BRANCHES[0]))
    info = geo.info()
    info["packs"]["reverse"]["sources"].clear()
    assert geo.info()["packs"]["reverse"]["sources"]
    explanation = geo.explain(answer)
    geo.close()
    assert explanation["result"] == answer.to_dict()
    assert explanation["raw_evidence_installed"] is False
    selected = answer.require_one()
    assert selected is not None and isinstance(selected.city, Place)
    with pytest.raises(FrozenInstanceError):
        selected.city.name = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        selected.city.evidence.source_ids[0]["id"] = "mutated"  # type: ignore[index]
    detached = answer.to_dict()
    detached["selected"]["city"]["evidence"]["source_ids"][0]["id"] = "mutated"
    assert (
        answer.to_dict()["selected"]["city"]["evidence"]["source_ids"][0]["id"] == "a"
    )
    ambiguous = replace(answer, status="ambiguous", selected=None)
    with pytest.raises(AmbiguousResultError):
        ambiguous.require_one()


@pytest.mark.parametrize(
    "value", [True, "12", None, float("nan"), float("inf"), 10**400]
)
def test_bad_coordinates(value: object) -> None:
    with Geocoder(PACK) as geo, pytest.raises(InvalidInputError):
        geo.reverse(value, 0)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value", [True, 0, "0" * 15, " 8860145b49fffff", "836014fffffffff"]
)
def test_bad_h3(value: object) -> None:
    with Geocoder(PACK) as geo, pytest.raises(InvalidInputError):
        geo.from_h3(value)  # type: ignore[arg-type]


def test_coordinate_normalization_and_logical_parent() -> None:
    with Geocoder(PACK) as geo:
        assert geo.reverse(0, 180) == geo.reverse(0, -180)
        for cell in [h3.get_pentagons(8)[0], h3.latlng_to_cell(-89.99, 0, 8)]:
            lat, lon = h3.cell_to_latlng(cell)
            actual = geo.reverse(lat, lon)
            expected = geo.from_h3(h3.int_to_str(cell).upper())
            assert actual.selected == expected.selected
            assert actual.reference == expected.reference
            assert expected.query.h3 == h3.int_to_str(cell)
        # This vertex converts directly to a different r3 cell. Only the logical
        # parent is present in the fixture, so a fresh coarse conversion is wrong.
        lat, lon = 12.450873670161915, 77.77098085188615
        cell = h3.latlng_to_cell(lat, lon, 8)
        assert h3.cell_to_parent(cell, 3) == ROOT
        assert h3.latlng_to_cell(lat, lon, 3) != ROOT
        actual = geo.reverse(lat, lon)
        expected = geo.from_h3(h3.int_to_str(cell))
        assert actual.status != "outside_coverage"
        assert actual.selected == expected.selected
        assert actual.reference == expected.reference

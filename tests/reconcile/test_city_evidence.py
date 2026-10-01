from __future__ import annotations

import json
from pathlib import Path

import pytest

from build_data.acquire import Workspace
from build_data.reconcile.build import build_country
from build_data.reconcile.common import connect, policy, unpack
from build_data.reconcile.lookup import Locator
from build_data.reconcile.spatial import create_areas, insert_area

from .conftest import area, place, write_inputs


@pytest.mark.parametrize("city_polygon", [False, True])
def test_ward_container_and_independent_suburb(
    city_polygon: bool, tmp_path: Path
) -> None:
    city = place("c", "Metropolis", 0.5, 0.5, source="overture")
    city["feature_class"] = "city"
    evidence = json.loads(city["provenance"])
    evidence["upstream"]["hierarchies"] = [
        [
            {"division_id": "ward", "subtype": "locality"},
            {"division_id": "c", "subtype": "locality"},
        ]
    ]
    city["provenance"] = json.dumps(evidence)
    suburb = place("s", "Independent town", 0.7, 0.7, source="overture")
    suburb["feature_class"] = "town"
    ward = place("ward", "Administrative unit", 0.50001, 0.50001, source="overture")
    ward["feature_class"] = None
    shapes = [
        area("nation", "Nation", "country", (0, 0, 2, 2)),
        area("ward", "Administrative unit", "locality", (0.3, 0.3, 0.6, 0.6)),
        area("s", "Independent town", "locality", (0.65, 0.65, 0.8, 0.8)),
    ]
    if city_polygon:
        shapes.append(area("c", "Metropolis", "locality", (0.1, 0.1, 1, 1)))
    root = write_inputs(
        tmp_path / "inputs",
        geonames=[
            place("1", "Metropolis", 0.5, 0.5, population=1000000),
            place("2", "Independent town", 0.7, 0.7, population=20000),
        ],
        divisions=[city, suburb, ward],
        areas=shapes,
    )
    output = build_country(Workspace(tmp_path), root, "ZZ", "inputs", policy(), "test")
    land = tmp_path / "land.sqlite"
    db = connect(land)
    create_areas(db)
    shape = area("land", "Land", "land", (0, 0, 2, 2))
    insert_area(db, "land", "land", 0, shape["geometry"], (0, 0, 2, 2), "test")
    db.commit()
    db.close()
    with Locator({"ZZ": output}, land, policy()) as locator:
        assert locator.locate(0.50001, 0.50001)["city"]["geonames_id"] == "1"
        assert locator.locate(0.7, 0.7)["city"]["geonames_id"] == "2"
        db = locator.countries["ZZ"]
        assert db.execute(
            "SELECT count(*) FROM areas WHERE entity='district:overture:ward'"
        ).fetchone() == (1,)
        assert not db.execute(
            "SELECT 1 FROM points WHERE entity='city:overture:ward'"
        ).fetchone()


def test_country_catalogue_without_claiming_a_polygon(tmp_path: Path) -> None:
    country = place("nation", "Territory", 0.5, 0.5, code="TERR")
    country["feature_class"] = "A"
    root = write_inputs(
        tmp_path / "inputs",
        geonames=[country, place("town", "Town", 0.5, 0.5)],
        divisions=[],
        areas=[],
    )
    output = build_country(Workspace(tmp_path), root, "ZZ", "inputs", policy(), "test")
    db = connect(output, readonly=True)
    try:
        value = unpack(
            db.execute("SELECT data FROM entities WHERE id='country:ZZ'").fetchone()[0]
        )
        assert value["name"] == "Territory"
        assert value["parent"] is None
        assert db.execute(
            "SELECT count(*) FROM areas WHERE role='country'"
        ).fetchone() == (0,)
    finally:
        db.close()


@pytest.mark.parametrize("same_identity", [True, False])
def test_region_requires_exact_city_identity(
    same_identity: bool, tmp_path: Path
) -> None:
    city = place("city", "City", 0.5, 0.5, source="overture", qid="Q1")
    city["feature_class"] = "city"
    region = place(
        "region",
        "Region",
        0.5,
        0.5,
        source="overture",
        subtype="region",
        qid="Q1" if same_identity else "Q2",
    )
    ward = place("ward", "Subunit", 0.51, 0.51, source="overture")
    ward["feature_class"] = None
    root = write_inputs(
        tmp_path / "inputs",
        geonames=[
            place("1", "City", 0.5, 0.5, population=1000000),
            place("2", "Subunit", 0.51, 0.51, population=20000),
        ],
        divisions=[city, region, ward],
        areas=[
            area("nation", "Nation", "country", (0, 0, 1, 1)),
            area("region", "Region", "region", (0, 0, 1, 1)),
            area("ward", "Subunit", "locality", (0.4, 0.4, 0.6, 0.6)),
        ],
        names=[
            {
                "source": "geonames",
                "source_id": "alias",
                "entity_source_id": "1",
                "language": "wkdt",
                "name": "Q1",
                "is_historic": False,
                "is_preferred": False,
                "is_short": False,
                "is_colloquial": False,
                "source_release": "test",
                "license": "CC BY 4.0",
                "provenance": "{}",
            }
        ],
    )
    output = build_country(Workspace(tmp_path), root, "ZZ", "inputs", policy(), "test")
    db = connect(output, readonly=True)
    try:
        from build_data.reconcile.lookup import choose_city, covering

        answer = choose_city(covering(db, 0.51, 0.51, "city"))
        assert answer is not None
        assert answer["geonames_id"] == "2"  # Preserve a linked town inside a region.
        outer = choose_city(covering(db, 0.2, 0.2, "city"))
        assert (outer or {}).get("geonames_id") == ("1" if same_identity else None)
    finally:
        db.close()


def test_shared_city_footprint_beats_unlinked_town_and_keeps_linked_town(
    tmp_path: Path,
) -> None:
    city = place(
        "county", "Metropolis", 0.5, 0.5, source="overture", subtype="county", qid="Q1"
    )
    weak = place("weak", "Unverified town", 0.2, 0.2, source="overture")
    strong = place("strong", "Independent town", 0.7, 0.7, source="overture")
    weak["feature_class"] = strong["feature_class"] = "town"
    root = write_inputs(
        tmp_path / "inputs",
        geonames=[
            place("1", "Metropolis", 0.5, 0.5, population=1000000),
            place("2", "Independent town", 0.7, 0.7, population=20000),
        ],
        divisions=[city, weak, strong],
        areas=[
            area("nation", "Nation", "country", (0, 0, 1, 1)),
            area("county", "Metropolis", "county", (0, 0, 1, 1)),
            area("weak", "Unverified town", "locality", (0.1, 0.1, 0.3, 0.3)),
            area("strong", "Independent town", "locality", (0.6, 0.6, 0.8, 0.8)),
        ],
        names=[
            {
                "source": "geonames",
                "source_id": "alias",
                "entity_source_id": "1",
                "language": "wkdt",
                "name": "Q1",
                "is_historic": False,
                "is_preferred": False,
                "is_short": False,
                "is_colloquial": False,
                "source_release": "test",
                "license": "CC BY 4.0",
                "provenance": "{}",
            }
        ],
    )
    output = build_country(Workspace(tmp_path), root, "ZZ", "inputs", policy(), "test")
    land = tmp_path / "land.sqlite"
    db = connect(land)
    create_areas(db)
    shape = area("land", "Land", "land", (0, 0, 1, 1))
    insert_area(db, "land", "land", 0, shape["geometry"], (0, 0, 1, 1), "test")
    db.commit()
    db.close()
    with Locator({"ZZ": output}, land, policy()) as locator:
        assert locator.locate(0.2, 0.2)["city"]["geonames_id"] == "1"
        assert locator.locate(0.7, 0.7)["city"]["geonames_id"] == "2"

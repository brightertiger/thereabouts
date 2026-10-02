"""Territorial locality ownership is independent of local settlement titles."""

import sqlite3
from pathlib import Path

import pytest
import shapely

from build_data.cities.footprints import screen
from build_data.reconcile.common import pack
from tests.test_city_normalization import city


@pytest.mark.parametrize("title", ["village", "hamlet", "town"])
def test_municipal_locality_keeps_its_polygon(tmp_path: Path, title: str) -> None:
    db = sqlite3.connect(tmp_path / "source.sqlite")
    db.execute(
        "CREATE TABLE areas(id INT,entity TEXT,role TEXT,priority INT,"
        "geometry BLOB,evidence BLOB)"
    )
    evidence = {"entity_id": "division", "subtype": "locality", "is_territorial": True}
    db.execute(
        "INSERT INTO areas VALUES(1,'municipality','city',20,?,?)",
        (shapely.box(0, 0, 1, 1).wkb, pack(evidence)),
    )
    # The linked GeoNames anchor is slightly outside; Overture's own is inside.
    cities = {"municipality": city("municipality", -0.001, 20000)}
    divisions = {"division": {"class": title, "longitude": 0.5, "latitude": 0.5}}
    accepted, rejected = screen(db, cities, divisions, {}, [], 250)
    assert len(accepted) == 1
    assert rejected == []
    # A weak village seat that failed eligibility cannot acquire a footprint.
    assert screen(db, {}, divisions, {}, [])[0] == []
    # The general locality rule never admits a county/container by rank alone.
    evidence["subtype"] = "county"
    db.execute("UPDATE areas SET evidence=?", (pack(evidence),))
    assert screen(db, cities, divisions, {}, [], 250)[0] == []
    db.close()


def test_distant_namesake_anchor_does_not_validate_a_city_boundary(
    tmp_path: Path,
) -> None:
    db = sqlite3.connect(tmp_path / "source.sqlite")
    db.execute(
        "CREATE TABLE areas(id INT,entity TEXT,role TEXT,priority INT,"
        "geometry BLOB,evidence BLOB)"
    )
    evidence = {"entity_id": "village", "subtype": "locality", "is_territorial": True}
    db.execute(
        "INSERT INTO areas VALUES(1,'capital','city',20,?,?)",
        (shapely.box(0, 0, 0.01, 0.01).wkb, pack(evidence)),
    )
    accepted, rejected = screen(
        db,
        {"capital": city("capital", 0.1, 1000000)},
        {"village": {"class": "village", "longitude": 0.005, "latitude": 0.005}},
        {},
        [],
        250,
    )
    assert accepted == []
    assert rejected[0]["reason"] == "anchor outside claimed boundary"
    db.close()


def test_linked_municipality_precedes_smaller_unlinked_overlap() -> None:
    from build_data.cities.footprints import resolve_overlaps

    municipal = {
        "city_id": "town",
        "method": "city_polygon",
        "priority": 1,
        "geometry": shapely.box(0, 0, 1, 1),
        "ownership_order": (-20, 1, -20000, "town"),
        "evidence": {},
    }
    small = {
        "city_id": "unlinked",
        "method": "city_polygon",
        "priority": 1,
        "geometry": shapely.box(0.5, 0, 1.5, 0.5),
        "ownership_order": (0, 0, 0.5, "unlinked"),
        "evidence": {},
    }
    result = {r["city_id"]: r for r in resolve_overlaps([small, municipal])}
    assert result["town"]["geometry"].equals(municipal["geometry"])
    assert not result["unlinked"]["geometry"].covers(shapely.Point(0.75, 0.25))


def test_city_rollup_preserves_accepted_part_boundary() -> None:
    from build_data.cities.footprints import resolve_overlaps, roll_up

    core = {
        "city_id": "city",
        "method": "policy_polygon",
        "priority": 0,
        "geometry": shapely.box(0, 0, 1, 1),
        "evidence": {},
    }
    part = {
        "city_id": "part",
        "method": "city_polygon",
        "priority": 1,
        "geometry": shapely.box(0.9, 0, 1.2, 0.2),
        "ownership_order": (-20, 0.06, -10000, "part"),
        "evidence": {},
    }
    neighbour = {
        "city_id": "neighbour",
        "method": "city_polygon",
        "priority": 1,
        "geometry": shapely.box(1.1, 0, 1.4, 0.2),
        "ownership_order": (0, 0, 0.06, "neighbour"),
        "evidence": {},
    }
    result = resolve_overlaps(roll_up([core, part, neighbour], {"part": "city"}))
    edge = shapely.Point(1.15, 0.1)
    assert {f["city_id"] for f in result if f["geometry"].covers(edge)} == {"city"}
    assert part["city_id"] == "part"  # Keep original audit geometry/identity intact.

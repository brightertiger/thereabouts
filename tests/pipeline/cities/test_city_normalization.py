"""Small synthetic spatial and policy tests; no network or production data."""

import sqlite3
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from pipeline.config.engines import EngineLimits
from pipeline.config.policies import cities as policy
from pipeline.engines.cities.candidates import eligible
from pipeline.engines.cities.engine import Engine
from pipeline.engines.cities.footprints import screen
from pipeline.engines.cities.urban import Urban
from pipeline.engines.reconcile.common import Row, pack


def make_engine(
    tmp_path: Path,
    cities: list[Row],
    footprints: list[Row],
    urban_shape: shapely.Polygon | None = None,
) -> Engine:
    source = tmp_path / "source.sqlite"
    db = sqlite3.connect(source)
    db.execute("CREATE TABLE points(entity TEXT,x REAL,y REAL)")
    db.executemany(
        "INSERT INTO points VALUES(?,?,?)",
        [(r["city_id"], r["longitude"], r["latitude"]) for r in cities],
    )
    db.commit()
    db.close()
    path = tmp_path / "index.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE cities(id TEXT,data BLOB);
      CREATE TABLE footprints(id INT,data BLOB,geometry BLOB);
      CREATE TABLE parts(place_id TEXT,city_id TEXT);
      CREATE TABLE rejected(area_id INT,city_id TEXT);
    """)
    db.executemany(
        "INSERT INTO cities VALUES(?,?)", [(r["city_id"], pack(r)) for r in cities]
    )
    for i, r in enumerate(footprints):
        db.execute(
            "INSERT INTO footprints VALUES(?,?,?)",
            (
                i,
                pack({k: v for k, v in r.items() if k != "geometry"}),
                r["geometry"].wkb,
            ),
        )
    db.commit()
    db.close()
    urban_path = tmp_path / "urban.parquet"
    pq.write_table(
        pa.table(
            {
                "entity_id": ["1"],
                "geometry": [
                    (
                        urban_shape
                        if urban_shape is not None
                        else shapely.box(-1, -1, 1, 1)
                    ).wkb
                ],
            }
        ),
        urban_path,
    )
    return Engine(
        path,
        source,
        Urban([{"path": str(urban_path)}]),
        policy(),
        limits=EngineLimits(),
    )


def city(identity: str, x: float, population: int) -> Row:
    return {
        "city_id": identity,
        "longitude": x,
        "latitude": 0.0,
        "population": population,
    }


def test_weak_village_seat_cannot_absorb() -> None:
    settings = policy()["eligibility"]
    assert eligible("PPLA4", 0, {"village"}, False, settings) is None
    assert eligible("PPLA3", 4000, {"hamlet"}, False, settings) is None
    assert eligible("PPLA3", 4000, {"town"}, False, settings)
    assert eligible("PPL", 15000, {"village"}, False, settings)
    assert eligible("PPLX", 500000, {"city"}, False, settings) is None
    assert eligible("PPLX", 500000, {"city"}, True, settings)


def test_boundary_cannot_expand_over_unbounded_neighbour(tmp_path: Path) -> None:
    engine = make_engine(
        tmp_path,
        [city("big", 0, 5000000), city("neighbour", 0.06, 50000)],
        [
            {
                "city_id": "big",
                "priority": 0,
                "method": "policy_polygon",
                "geometry": shapely.box(-0.04, -0.04, 0.04, 0.04),
            }
        ],
    )
    ids, methods = engine.overlay(
        np.array([[0.0, 0.03], [0.0, 0.045], [0.0, 0.065]]), False
    )
    assert ids.tolist() == ["big", "neighbour", "neighbour"]
    assert methods.tolist() == [
        "policy_polygon",
        "urban_allocation",
        "urban_allocation",
    ]


def test_radius_optional_and_rural_fifty_km_cutoff(tmp_path: Path) -> None:
    engine = make_engine(
        tmp_path, [city("town", 0, 10000)], [], shapely.box(10, 10, 11, 11)
    )
    coordinates = np.array([[0.0, 0.002], [0.0, 0.4], [0.0, 0.5]])
    off, _ = engine.overlay(coordinates, False)
    on, methods = engine.overlay(coordinates, True)
    assert off.tolist() == [None, None, None]
    assert on.tolist() == ["town", None, None]
    assert methods[0] == "town_radius"
    ids, methods = engine.apply(
        coordinates,
        np.array(["town", "town", None], dtype=object),
        np.array(["nearest", "nearest", None], dtype=object),
        False,
    )
    assert ids.tolist() == ["town", "town", None]
    assert methods.tolist() == ["rural_nearest", "rural_nearest_distant", None]


def test_township_polygon_rejected_but_identity_retained(tmp_path: Path) -> None:
    db = sqlite3.connect(tmp_path / "areas.sqlite")
    db.execute(
        "CREATE TABLE areas(id INT,entity TEXT,role TEXT,priority INT,"
        "geometry BLOB,evidence BLOB)"
    )
    evidence = {
        "entity_id": "division",
        "subtype": "locality",
        "provenance": '{"upstream":{"names":{"primary":"A Township"}}}',
    }
    db.execute(
        "INSERT INTO areas VALUES(1,'town','city',20,?,?)",
        (shapely.box(-1, -1, 1, 1).wkb, pack(evidence)),
    )
    cities = {"town": city("town", 0, 20000)}
    accepted, rejected = screen(
        db,
        cities,
        {"division": {"class": "town"}},
        {"container_terms": ["township"]},
        [],
    )
    assert accepted == []
    assert rejected[0]["area_id"] == 1
    assert "town" in cities
    db.close()


def test_source_anchor_just_outside_urban_grid_keeps_neighbour_core(
    tmp_path: Path,
) -> None:
    engine = make_engine(
        tmp_path,
        [city("large", 0.05, 1000000), city("town", -0.001, 35000)],
        [],
        shapely.box(0, -1, 1, 1),
    )
    ids, _ = engine.overlay(np.array([[0.0, 0.001], [0.0, 0.003]]), False)
    assert ids.tolist() == ["town", "town"]


def test_radius_uses_farther_town_when_nearest_radius_does_not_reach() -> None:
    from pipeline.engines.cities.radius import assign
    from pipeline.engines.geo.sphere import unit_vectors

    coords = np.array([[0.0, 0.0]])
    anchors = unit_vectors(np.array([[0.0, 0.009], [0.0, 0.010]]))
    actual = assign(
        coords,
        anchors,
        np.array([5000.0, 50000.0]),
        np.array(["small", "large"], dtype=object),
        policy()["town_radius"],
    )
    assert actual.tolist() == ["large"]

"""The store owns the country artifact without changing a byte or a row order."""

import ast
import re
import sqlite3
from pathlib import Path

import shapely

from pipeline.engines.reconcile.entities import make_entity
from pipeline.engines.store import areas, catalog, entities, schema
from pipeline.engines.store.codec import pack
from pipeline.engines.store.types import Entity

REPOSITORY = Path(__file__).parents[2]

# The DDL as reconcile/{entities,matching,spatial,hierarchy}.py wrote it at
# 141cfab; sqlite_master stores this text, so the artifact bytes depend on it.
OLD_DDL = [
    """
        CREATE TABLE entities (id TEXT PRIMARY KEY, role TEXT, data TEXT);
        CREATE TABLE points (id INTEGER PRIMARY KEY, entity TEXT, x REAL, y REAL);
        CREATE VIRTUAL TABLE point_bounds USING rtree(id,xmin,xmax,ymin,ymax);
        CREATE TABLE metadata (key TEXT PRIMARY KEY, data TEXT);
    """,
    """
        CREATE TABLE geonames (id TEXT PRIMARY KEY, class TEXT, code TEXT,
          admin1 TEXT, population INTEGER, x REAL, y REAL, data TEXT);
        CREATE TABLE names (name TEXT, id TEXT, PRIMARY KEY(name,id)) WITHOUT ROWID;
        CREATE TABLE wikidata (qid TEXT, id TEXT, PRIMARY KEY(qid,id)) WITHOUT ROWID;
        CREATE TABLE divisions (id TEXT PRIMARY KEY, subtype TEXT, link TEXT,
          method TEXT, distance_m REAL, data TEXT, issue TEXT);
        CREATE INDEX gn_xy ON geonames(x,y);
    """,
    """
        CREATE TABLE areas (id INTEGER PRIMARY KEY, entity TEXT, role TEXT,
          priority INTEGER, geometry BLOB NOT NULL, evidence TEXT);
        CREATE VIRTUAL TABLE area_bounds USING rtree(id,xmin,xmax,ymin,ymax);
        CREATE INDEX area_entity ON areas(entity,role);
    """,
    "CREATE TABLE state_codes(entity TEXT PRIMARY KEY, data BLOB)",
]
ARTIFACT_TABLES = (
    "entities|points|point_bounds|metadata|geonames|names|wikidata|divisions|"
    "areas|area_bounds|state_codes"
)
# SQL keywords are upper case in this codebase; prose such as "table names" is not.
ARTIFACT_SQL = re.compile(rf"\b(FROM|JOIN|INTO|UPDATE|TABLE)\s+({ARTIFACT_TABLES})\b")


def master(db: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return db.execute(
        "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
    ).fetchall()


def test_schema_text_is_unchanged() -> None:
    old, new = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
    for script in OLD_DDL:
        old.executescript(script)
    schema.create_entities(new)
    schema.create_catalog(new)
    schema.create_areas(new)
    schema.create_state_codes(new)
    assert master(new) == master(old)


def place(identity: str, population: int, x: float) -> dict[str, object]:
    return {
        "source": "geonames",
        "source_id": identity,
        "feature_class": "P",
        "feature_code": "PPL",
        "admin1_code": "01",
        "population": population,
        "longitude": x,
        "latitude": 1.0,
        "name": "Place " + identity,
    }


def fixture() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    schema.create_entities(db)
    schema.create_catalog(db)
    schema.create_areas(db)
    schema.create_state_codes(db)
    # Insertion order differs from key order, so unordered reads would show it.
    for identity, role in [("c:2", "city"), ("s:1", "state"), ("c:1", "city")]:
        entities.put_entity(db, {"id": identity, "role": role, "name": identity})
        entities.add_point(db, identity, 2.0, 1.0)
    entities.add_point(db, "c:1", 1.0, 1.0)
    for identity, population in [("9", 20000), ("10", 15000), ("8", 100)]:
        catalog.put_geonames(db, place(identity, population, float(identity)))
    catalog.put_wikidata(db, "Q2", "9")
    catalog.put_wikidata(db, "Q1", "10")
    for identity, shape in [("c:2", (0, 0, 2, 2)), ("c:1", (1, 1, 3, 3))]:
        geometry = shapely.box(*shape)
        areas.insert_area(
            db, identity, "city", 1, geometry.wkb, geometry.bounds, pack({})
        )
    entities.put_state_code(db, "s:1", {"geonames_admin1": "01"})
    entities.put_metadata(db, "policy", '{"a":1}')
    return db


def test_accessors_return_the_inline_queries_rows_in_their_order() -> None:
    db = fixture()
    assert [e["id"] for e in entities.entities(db)] == ["c:1", "c:2", "s:1"]
    assert [i for i, _, _ in entities.entities_in_roles(db, ("city",))] == [
        i for (i,) in db.execute("SELECT id FROM entities WHERE role='city'")
    ]
    assert entities.find_entity(db, "missing") is None
    assert entities.entity_point(db, "c:1") == (2.0, 1.0)
    assert (
        entities.points(db)
        == db.execute(
            "SELECT DISTINCT entity,x,y FROM points ORDER BY entity,x,y"
        ).fetchall()
    )
    assert [r[0] for r in entities.anchored_entities(db)] == ["c:1", "c:2", "s:1"]
    assert entities.metadata(db, "policy") == {"a": 1}
    assert [i for i, _ in entities.state_codes(db)] == ["s:1"]
    assert [p["source_id"] for p in catalog.geonames_places(db, "P", 15000)] == [
        "10",
        "9",
    ]
    assert catalog.geonames_point(db, "9") == (9.0, 1.0)
    assert catalog.geonames_class(db, "8") == "P"
    assert (
        list(catalog.wikidata_links(db))
        == db.execute("SELECT qid,id FROM wikidata").fetchall()
    )
    assert [r[0] for r in areas.areas_by_role(db, "city")] == [1, 2]
    assert [r[0] for r in areas.entity_areas(db, "c:1", "city")] == [2]
    assert list(areas.entity_areas(db, "c:1", "city", priority=0)) == []
    windows = [(-1.0, 0.5, -1.0, 0.5), (2.5, 4.0, 2.5, 4.0)]
    assert [r[0] for r in areas.intersecting_any(db, windows, "city")] == [1, 2]
    assert areas.area_bounds(db, 2) == (1.0, 3.0, 1.0, 3.0)


def test_entity_type_names_every_canonical_key() -> None:
    row = {
        "source": "overture",
        "source_id": "o1",
        "source_release": "r",
        "license": "l",
        "provenance": "{}",
        "name": "Name",
    }
    value = make_entity(row, "city", "LU", {"sovereigns": {}})
    assert set(value) == set(Entity.__required_keys__)


def test_no_artifact_sql_outside_the_store_and_its_producer() -> None:
    roots = [
        "pipeline/engines/cells",
        "pipeline/engines/cities",
        "pipeline/engines/normalize_cells",
        "pipeline/stages",
        "pipeline/content",
        "pipeline/release",
        "pipeline/tools",
    ]
    found = []
    for root in roots:
        for path in sorted((REPOSITORY / root).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_bytes())):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and ARTIFACT_SQL.search(node.value)
                ):
                    found.append(f"{path.relative_to(REPOSITORY)}:{node.lineno}")
    assert not found

"""The artifact's DDL. SQLite stores each statement's text, so keep it verbatim."""

from __future__ import annotations

import sqlite3


def create_entities(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE entities (id TEXT PRIMARY KEY, role TEXT, data TEXT);
        CREATE TABLE points (id INTEGER PRIMARY KEY, entity TEXT, x REAL, y REAL);
        CREATE VIRTUAL TABLE point_bounds USING rtree(id,xmin,xmax,ymin,ymax);
        CREATE TABLE metadata (key TEXT PRIMARY KEY, data TEXT);
    """)


def create_catalog(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE geonames (id TEXT PRIMARY KEY, class TEXT, code TEXT,
          admin1 TEXT, population INTEGER, x REAL, y REAL, data TEXT);
        CREATE TABLE names (name TEXT, id TEXT, PRIMARY KEY(name,id)) WITHOUT ROWID;
        CREATE TABLE wikidata (qid TEXT, id TEXT, PRIMARY KEY(qid,id)) WITHOUT ROWID;
        CREATE TABLE divisions (id TEXT PRIMARY KEY, subtype TEXT, link TEXT,
          method TEXT, distance_m REAL, data TEXT, issue TEXT);
        CREATE INDEX gn_xy ON geonames(x,y);
    """)


def create_areas(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE areas (id INTEGER PRIMARY KEY, entity TEXT, role TEXT,
          priority INTEGER, geometry BLOB NOT NULL, evidence TEXT);
        CREATE VIRTUAL TABLE area_bounds USING rtree(id,xmin,xmax,ymin,ymax);
        CREATE INDEX area_entity ON areas(entity,role);
    """)


def create_state_codes(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE state_codes(entity TEXT PRIMARY KEY, data BLOB)")

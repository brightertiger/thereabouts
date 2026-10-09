"""The GeoNames catalogue, its name and Wikidata keys, and linked divisions.

Statements keep their original text: rows without an ORDER BY come back in
plan order, and outputs depend on that order.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from typing import cast

from .codec import Row, pack, unpack
from .types import Division


def put_geonames(db: sqlite3.Connection, row: Row) -> None:
    db.execute(
        "INSERT INTO geonames VALUES(?,?,?,?,?,?,?,?)",
        (
            row["source_id"],
            row["feature_class"],
            row["feature_code"],
            row["admin1_code"],
            row["population"],
            row["longitude"],
            row["latitude"],
            pack(row),
        ),
    )


def put_names(db: sqlite3.Connection, names: Iterable[tuple[str, str]]) -> None:
    """(name key, GeoNames id) pairs; duplicates are ignored."""
    db.executemany("INSERT OR IGNORE INTO names VALUES(?,?)", names)


def put_wikidata(db: sqlite3.Connection, qid: str, identity: str) -> None:
    db.execute("INSERT OR IGNORE INTO wikidata VALUES(?,?)", (qid, identity))


def geonames_place(db: sqlite3.Connection, identity: str | None) -> Row | None:
    value = db.execute("SELECT data FROM geonames WHERE id=?", (identity,)).fetchone()
    return None if value is None else unpack(value[0])


def geonames_point(
    db: sqlite3.Connection, identity: str | None
) -> tuple[float, float] | None:
    value = db.execute("SELECT x,y FROM geonames WHERE id=?", (identity,)).fetchone()
    return None if value is None else (value[0], value[1])


def geonames_class(db: sqlite3.Connection, identity: str | None) -> str | None:
    value = db.execute("SELECT class FROM geonames WHERE id=?", (identity,)).fetchone()
    return None if value is None else cast(str | None, value[0])


def geonames_places(
    db: sqlite3.Connection, feature_class: str, minimum_population: int
) -> Iterator[Row]:
    """One feature class at or above a population, in id order."""
    for (data,) in db.execute(
        "SELECT data FROM geonames WHERE class=? AND population>=? ORDER BY id",
        (feature_class, minimum_population),
    ):
        yield unpack(data)


def wikidata_links(db: sqlite3.Connection) -> Iterator[tuple[str, str]]:
    """(QID, GeoNames id) pairs in key order."""
    yield from db.execute("SELECT qid,id FROM wikidata")


def put_division(
    db: sqlite3.Connection,
    row: Row,
    linked: str | None,
    method: str,
    metres: float | None,
    issue: str | None,
) -> None:
    db.execute(
        "INSERT INTO divisions VALUES(?,?,?,?,?,?,?)",
        (row["source_id"], row["subtype"], linked, method, metres, pack(row), issue),
    )


def divisions(db: sqlite3.Connection) -> Iterator[tuple[str, str | None, Division]]:
    """(division id, linked GeoNames id, the division) in table order."""
    for identity, link, data in db.execute("SELECT id,link,data FROM divisions"):
        yield identity, link, cast(Division, unpack(data))

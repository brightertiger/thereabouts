"""SQLite R-trees and bounded geometry access."""

from __future__ import annotations

import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Iterator

import shapely
from shapely.geometry.base import BaseGeometry


class _Decoded(threading.local):
    """Prepared geometries are per thread: GEOS prepares lazily on first use."""

    def __init__(self) -> None:
        self.values: OrderedDict[bytes, BaseGeometry] = OrderedDict()
        self.bytes = 0


_DECODED = _Decoded()


def decode(wkb: bytes) -> BaseGeometry:
    cache = _DECODED
    if wkb in cache.values:
        cache.values.move_to_end(wkb)
        return cache.values[wkb]
    geometry = shapely.from_wkb(wkb)
    while cache.values and cache.bytes + len(wkb) > 32_000_000:
        previous, _ = cache.values.popitem(last=False)
        cache.bytes -= len(previous)
    if len(wkb) <= 32_000_000:
        cache.values[wkb] = geometry
        cache.bytes += len(wkb)
        shapely.prepare(geometry)
    return geometry


def create_areas(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE areas (id INTEGER PRIMARY KEY, entity TEXT, role TEXT,
          priority INTEGER, geometry BLOB NOT NULL, evidence TEXT);
        CREATE VIRTUAL TABLE area_bounds USING rtree(id,xmin,xmax,ymin,ymax);
        CREATE INDEX area_entity ON areas(entity,role);
    """)


def insert_area(
    db: sqlite3.Connection,
    entity: str,
    role: str,
    priority: int,
    wkb: bytes,
    bounds: tuple[float, float, float, float],
    evidence: bytes | str,
) -> None:
    rowid = db.execute(
        "INSERT INTO areas VALUES(NULL,?,?,?,?,?)",
        (entity, role, priority, wkb, evidence),
    ).lastrowid
    x, y, a, b = bounds
    db.execute("INSERT INTO area_bounds VALUES(?,?,?,?,?)", (rowid, x, a, y, b))


def intersecting(
    db: sqlite3.Connection,
    bounds: tuple[float, float, float, float],
    role: str | None = None,
) -> Iterator[tuple[int, str, str, int, bytes, bytes | str]]:
    x, a, y, b = bounds
    sql = (
        "SELECT a.* FROM area_bounds r JOIN areas a ON a.id=r.id "
        "WHERE r.xmin<=? AND r.xmax>=? AND r.ymin<=? AND r.ymax>=?"
    )
    args: list[object] = [a, x, b, y]
    if role is not None:
        sql += " AND a.role=?"
        args.append(role)
    yield from db.execute(sql, args)


def containing(
    db: sqlite3.Connection, x: float, y: float, role: str | None = None
) -> Iterator[tuple[str, str, int, BaseGeometry]]:
    point = shapely.Point(x, y)
    for _, entity, kind, priority, wkb, _ in intersecting(db, (x, x, y, y), role):
        geometry = decode(wkb)
        if geometry.covers(point):
            yield entity, kind, priority, geometry

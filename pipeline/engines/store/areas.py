"""Polygon areas and their R-tree bounds, shared by country and land artifacts."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

# (id, entity, role, priority, WKB geometry, packed evidence)
Area = tuple[int, str, str, int, bytes, bytes | str]
# (west, east, south, north), the order R-tree columns use.
Window = tuple[float, float, float, float]


def insert_area(
    db: sqlite3.Connection,
    entity: str,
    role: str,
    priority: int,
    wkb: bytes,
    bounds: tuple[float, float, float, float],
    evidence: bytes | str,
) -> None:
    """`bounds` is (xmin, ymin, xmax, ymax), as shapely reports it."""
    rowid = db.execute(
        "INSERT INTO areas VALUES(NULL,?,?,?,?,?)",
        (entity, role, priority, wkb, evidence),
    ).lastrowid
    x, y, a, b = bounds
    db.execute("INSERT INTO area_bounds VALUES(?,?,?,?,?)", (rowid, x, a, y, b))


def intersecting(
    db: sqlite3.Connection,
    bounds: Window,
    role: str | None = None,
) -> Iterator[Area]:
    """Areas whose R-tree box meets the window, in R-tree traversal order."""
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


def intersecting_any(
    db: sqlite3.Connection, windows: list[Window], role: str | None = None
) -> list[Area]:
    """Areas meeting any window, each once; one role keeps R-tree order."""
    if len(windows) == 1:
        return list(intersecting(db, windows[0], role))
    found = {r[0]: r for window in windows for r in intersecting(db, window, role)}
    if role is None or not found:
        return list(found.values())
    # Preserve the scalar R-tree traversal order across the union. Read only
    # IDs from the broad envelope, never all its geometries and entity blobs.
    query = (
        "SELECT r.id FROM area_bounds r JOIN areas a ON a.id=r.id "
        "WHERE r.xmin<=? AND r.xmax>=? AND r.ymin<=? AND r.ymax>=? AND a.role=?"
    )
    args = (
        max(w[1] for w in windows),
        min(w[0] for w in windows),
        max(w[3] for w in windows),
        min(w[2] for w in windows),
        role,
    )
    return [found[i] for (i,) in db.execute(query, args) if i in found]


def area_bounds(db: sqlite3.Connection, area: int) -> Window:
    """An area's R-tree box (float32, rounded outward) as (west, east, south, north)."""
    value: Window = db.execute(
        "SELECT xmin,xmax,ymin,ymax FROM area_bounds WHERE id=?", (area,)
    ).fetchone()
    return value


def entity_areas(
    db: sqlite3.Connection, entity: str, role: str, priority: int | None = None
) -> Iterator[tuple[int, bytes]]:
    """(id, WKB) of one entity's areas in one role, in id order."""
    query = "SELECT id,geometry FROM areas WHERE entity=? AND role=?"
    parameters: list[str | int] = [entity, role]
    if priority is not None:
        query += " AND priority=?"
        parameters.append(priority)
    yield from db.execute(query, parameters)


def areas_by_role(
    db: sqlite3.Connection, role: str | None = None
) -> Iterator[tuple[int, str, int, bytes, bytes | str]]:
    """(id, entity, priority, WKB, evidence) of every area, or one role's, by id."""
    query = "SELECT id,entity,priority,geometry,evidence FROM areas"
    parameters: tuple[str, ...] = ()
    if role is not None:
        query += " WHERE role=?"
        parameters = (role,)
    yield from db.execute(query + " ORDER BY id", parameters)

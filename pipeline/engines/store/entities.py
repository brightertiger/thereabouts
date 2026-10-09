"""Canonical entities, their anchor points, metadata and state-code crosswalks.

Statements keep their original text: rows without an ORDER BY come back in
plan order, and outputs depend on that order.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from typing import Any, cast

from pipeline.errors import ArtifactIntegrityError

from .codec import Row, pack, unpack
from .types import Entity


def find_entity(db: sqlite3.Connection, identity: str) -> Entity | None:
    value = db.execute("SELECT data FROM entities WHERE id=?", (identity,)).fetchone()
    return None if value is None else cast(Entity, unpack(value[0]))


def entity(db: sqlite3.Connection, identity: str) -> Entity:
    value = find_entity(db, identity)
    if value is None:
        raise ArtifactIntegrityError(f"Dangling canonical identity: {identity}")
    return value


def entities(db: sqlite3.Connection) -> Iterator[Entity]:
    for (data,) in db.execute("SELECT data FROM entities ORDER BY id"):
        yield cast(Entity, unpack(data))


def country_entity(db: sqlite3.Connection) -> Entity | None:
    value = db.execute(
        "SELECT data FROM entities WHERE role='country' ORDER BY id LIMIT 1"
    ).fetchone()
    return None if value is None else cast(Entity, unpack(value[0]))


def entities_in_roles(
    db: sqlite3.Connection, roles: Sequence[str]
) -> Iterator[tuple[str, str, Entity]]:
    """(id, role, entity) in table order; `role` has no index, so this scans."""
    marks = ",".join("?" * len(roles))
    # Only placeholders are interpolated; roles are bound as parameters.
    query = f"SELECT id,role,data FROM entities WHERE role IN ({marks})"  # noqa: S608
    for identity, role, data in db.execute(query, tuple(roles)):
        yield identity, role, cast(Entity, unpack(data))


def put_entity(db: sqlite3.Connection, value: Entity | Row) -> None:
    db.execute(
        "INSERT OR REPLACE INTO entities VALUES(?,?,?)",
        (value["id"], value["role"], pack(value)),
    )


def update_entity(db: sqlite3.Connection, identity: str, value: Row) -> None:
    db.execute("UPDATE entities SET data=? WHERE id=?", (pack(value), identity))


def add_point(db: sqlite3.Connection, entity: str, x: float, y: float) -> None:
    rowid = db.execute(
        "INSERT INTO points VALUES(NULL,?,?,?)", (entity, x, y)
    ).lastrowid
    db.execute("INSERT INTO point_bounds VALUES(?,?,?,?,?)", (rowid, x, x, y, y))


def points(db: sqlite3.Connection) -> list[tuple[str, float, float]]:
    """Distinct (entity, x, y) anchors, sorted."""
    return db.execute(
        "SELECT DISTINCT entity,x,y FROM points ORDER BY entity,x,y"
    ).fetchall()


def entity_point(db: sqlite3.Connection, identity: str) -> tuple[float, float] | None:
    """An entity's first recorded anchor point."""
    value = db.execute(
        "SELECT x,y FROM points WHERE entity=? ORDER BY id LIMIT 1", (identity,)
    ).fetchone()
    return None if value is None else (value[0], value[1])


def anchored_entities(db: sqlite3.Connection) -> sqlite3.Cursor:
    """(id, role, x, y) for every entity in id order; x, y is its first anchor."""
    # A bounded temporary aggregate avoids a point query per catalogue entity.
    db.execute(
        "CREATE TEMP TABLE anchors AS SELECT entity,min(id) AS id "
        "FROM points GROUP BY entity"
    )
    db.execute("CREATE INDEX temp.anchor_entity ON anchors(entity)")
    return db.execute(
        "SELECT e.id,e.role,p.x,p.y FROM entities e "
        "LEFT JOIN anchors a ON e.id=a.entity "
        "LEFT JOIN points p ON p.id=a.id ORDER BY e.id"
    )


def put_metadata(db: sqlite3.Connection, key: str, value: str) -> None:
    """`value` is canonical JSON text."""
    db.execute("INSERT INTO metadata VALUES(?,?)", (key, value))


def metadata(db: sqlite3.Connection, key: str) -> Any:
    value = db.execute("SELECT data FROM metadata WHERE key=?", (key,)).fetchone()
    return None if value is None else json.loads(value[0])


def put_state_code(db: sqlite3.Connection, identity: str, match: Row) -> None:
    db.execute("INSERT INTO state_codes VALUES(?,?)", (identity, pack(match)))


def state_codes(db: sqlite3.Connection) -> Iterator[tuple[str, Row]]:
    """(state entity, its GeoNames ADM1 crosswalk evidence) in table order."""
    for identity, data in db.execute("SELECT entity,data FROM state_codes"):
        yield identity, unpack(data)

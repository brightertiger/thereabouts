"""Canonical identities and field-specific naming provenance."""

from __future__ import annotations

import json
import sqlite3

from .common import Row, pack, unpack


def create_entities(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE entities (id TEXT PRIMARY KEY, role TEXT, data TEXT);
        CREATE TABLE points (id INTEGER PRIMARY KEY, entity TEXT, x REAL, y REAL);
        CREATE VIRTUAL TABLE point_bounds USING rtree(id,xmin,xmax,ymin,ymax);
        CREATE TABLE metadata (key TEXT PRIMARY KEY, data TEXT);
    """)


def entity_id(row: Row, role: str, country: str, match: Row | None = None) -> str:
    if role == "country":
        return f"country:{country}"
    identity = match if match and role == "city" else row
    source_id = identity.get("entity_id", identity["source_id"])
    return f"{role}:{identity['source']}:{source_id}"


def make_entity(
    row: Row,
    role: str,
    country: str,
    policy: Row,
    match: Row | None = None,
    link: Row | None = None,
) -> Row:
    source = row["source"]
    name = row.get("name_en")
    name_source = source
    language = "en" if name else None
    if not name and match and match.get("name_en"):
        name, name_source, language = match["name_en"], "geonames", "en"
    if not name:
        name = row.get("name") or (match or {}).get("name")
    sources = [{"source": source, "id": row.get("entity_id", row["source_id"])}]
    provenance = [
        {
            "source": source,
            "release": row["source_release"],
            "license": row["license"],
            "evidence": json.loads(row["provenance"]),
        }
    ]
    if match and source != "geonames":
        sources.append({"source": "geonames", "id": match["source_id"]})
        provenance.append(
            {
                "source": "geonames",
                "release": match["source_release"],
                "license": match["license"],
                "evidence": json.loads(match["provenance"]),
            }
        )
    return {
        "id": entity_id(row, role, country, match),
        "role": role,
        "name": name,
        "local_name": row.get("name"),
        "country_code": country,
        "code": country
        if role == "country"
        else row.get("subdivision_code")
        if role == "state"
        else None,
        "code_status": "user-assigned"
        if country == "XK" and role == "country"
        else "source",
        "parent": None if role == "country" else f"country:{country}",
        "population": (match or row).get("population"),
        "geonames_id": (match or {}).get("source_id")
        if source != "geonames"
        else row["source_id"],
        "geonames_admin1": (match or (row if source == "geonames" else {})).get(
            "admin1_code"
        ),
        "feature_code": (match or row).get("feature_code"),
        "source_ids": sources,
        "provenance": provenance,
        "link": link,
        "name_provenance": {"source": name_source, "language": language},
        "sovereign": policy["sovereigns"].get(country),
    }


def save_entity(db: sqlite3.Connection, entity: Row) -> None:
    previous = db.execute(
        "SELECT data FROM entities WHERE id=?", (entity["id"],)
    ).fetchone()
    if previous:
        old = unpack(previous[0])
        # Deterministic preference for explicitly English Overture names. All
        # attached division identities remain discoverable in divisions/areas.
        if old["name_provenance"] == {"source": "overture", "language": "en"}:
            return
        if (
            entity["name_provenance"] == {"source": "geonames", "language": "en"}
            and old["name_provenance"]["source"] == "overture"
        ):
            return
    db.execute(
        "INSERT OR REPLACE INTO entities VALUES(?,?,?)",
        (entity["id"], entity["role"], pack(entity)),
    )


def add_point(db: sqlite3.Connection, entity: str, x: float, y: float) -> None:
    rowid = db.execute(
        "INSERT INTO points VALUES(NULL,?,?,?)", (entity, x, y)
    ).lastrowid
    db.execute("INSERT INTO point_bounds VALUES(?,?,?,?,?)", (rowid, x, x, y, y))


def fallback_points(db: sqlite3.Connection, country: str, policy: Row) -> None:
    for (data,) in db.execute("SELECT data FROM geonames WHERE class='P' ORDER BY id"):
        row = unpack(data)
        if row["feature_code"] not in policy["settlement_codes"]:
            continue
        entity = make_entity(row, "city", country, policy)
        save_entity(db, entity)
        add_point(db, entity["id"], row["longitude"], row["latitude"])
    db.commit()

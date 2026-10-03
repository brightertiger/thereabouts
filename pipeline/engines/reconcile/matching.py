"""Conservative, audited division-to-GeoNames identity links."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .common import Row, encode, key, pack, rows, unpack
from .spatial import distance


def prepare_catalog(db: sqlite3.Connection, root: Path) -> None:
    db.executescript("""
        CREATE TABLE geonames (id TEXT PRIMARY KEY, class TEXT, code TEXT,
          admin1 TEXT, population INTEGER, x REAL, y REAL, data TEXT);
        CREATE TABLE names (name TEXT, id TEXT, PRIMARY KEY(name,id)) WITHOUT ROWID;
        CREATE TABLE wikidata (qid TEXT, id TEXT, PRIMARY KEY(qid,id)) WITHOUT ROWID;
        CREATE TABLE divisions (id TEXT PRIMARY KEY, subtype TEXT, link TEXT,
          method TEXT, distance_m REAL, data TEXT, issue TEXT);
        CREATE INDEX gn_xy ON geonames(x,y);
    """)
    for row in rows(root / "geonames_places.parquet"):
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
        provenance = json.loads(row["provenance"])
        aliases = {row["name"], row["name_en"], provenance.get("asciiname")}
        aliases.update(provenance.get("alternate_names_untyped", "").split(","))
        db.executemany(
            "INSERT OR IGNORE INTO names VALUES(?,?)",
            (
                (name, row["source_id"])
                for name in sorted({key(a) for a in aliases})
                if name
            ),
        )
    for row in rows(root / "geonames_names.parquet"):
        if not row["is_historic"] and not row["valid_to"]:
            qid = row["name"].rsplit("/", 1)[-1]
            if qid.startswith("Q") and qid[1:].isdigit():
                db.execute(
                    "INSERT OR IGNORE INTO wikidata VALUES(?,?)",
                    (qid, row["entity_source_id"]),
                )
    db.commit()


def candidates(db: sqlite3.Connection, row: Row, field: str) -> list[Row]:
    upstream = json.loads(row["provenance"]).get("upstream", {})
    if field == "wikidata":
        keys = {upstream.get("wikidata")}
        column = "qid"
    else:
        keys = {key(row["name"]), key(row["name_en"])}
        column = "name"
    result: dict[str, Row] = {}
    for value in sorted(v for v in keys if v):
        for (data,) in db.execute(
            f"SELECT g.data FROM {field} n JOIN geonames g ON g.id=n.id "
            f"WHERE n.{column}=?",
            (value,),
        ):
            item = unpack(data)
            result[item["source_id"]] = item
    return list(result.values())


def link(
    db: sqlite3.Connection, row: Row, policy: Row
) -> tuple[str | None, str, float | None, str | None]:
    kind = row["subtype"]
    issue = None
    for method, cutoff in (
        ("wikidata", policy["wikidata_match_m"]),
        ("names", policy["name_match_m"]),
    ):
        matches = candidates(db, row, method)
        allowed = "A" if kind in ("region", "country", "dependency") else "P"
        matches = [m for m in matches if m["feature_class"] == allowed]
        ranked = sorted(
            (
                distance(
                    row["longitude"], row["latitude"], m["longitude"], m["latitude"]
                ),
                m["source_id"],
            )
            for m in matches
        )
        ranked = [(d, i) for d, i in ranked if d <= cutoff]
        if not ranked:
            if matches:
                issue = f"{method}: identity outside distance guard"
            continue
        if len(ranked) > 1 and (
            method == "wikidata" or ranked[1][0] < max(1000, ranked[0][0] * 2)
        ):
            issue = f"{method}: ambiguous candidates {encode(ranked)}"
            continue
        d, source_id = ranked[0]
        return source_id, method, d, issue
    return None, "unlinked", None, issue


def default_perspective(row: Row) -> bool:
    value = json.loads(row["provenance"]).get("upstream", {}).get("perspectives")
    # Overture includes/excludes are explicit alternate views. A default claim
    # has no restriction or an excludes list; an includes-only claim is alternate.
    return not value or not value.get("includes")


def link_divisions(db: sqlite3.Connection, root: Path, policy: Row) -> None:
    for row in rows(root / "overture_places.parquet"):
        if not default_perspective(row):
            continue
        linked, method, metres, issue = link(db, row, policy)
        db.execute(
            "INSERT INTO divisions VALUES(?,?,?,?,?,?,?)",
            (
                row["source_id"],
                row["subtype"],
                linked,
                method,
                metres,
                pack(row),
                issue,
            ),
        )
    db.commit()


def division(
    db: sqlite3.Connection, source_id: str
) -> tuple[Row | None, Row | None, Row]:
    result = db.execute(
        "SELECT data,link,method,distance_m,issue FROM divisions WHERE id=?",
        (source_id,),
    ).fetchone()
    if not result:
        return None, None, {}
    data, linked, method, metres, issue = result
    match = db.execute("SELECT data FROM geonames WHERE id=?", (linked,)).fetchone()
    return (
        unpack(data),
        unpack(match[0]) if match else None,
        {"method": method, "distance_m": metres, "issue": issue},
    )

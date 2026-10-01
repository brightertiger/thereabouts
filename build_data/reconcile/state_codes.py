"""GeoNames administrative crosswalks, with source-evidence-only votes."""

from __future__ import annotations

import json
import sqlite3

from .common import Row, key, unpack
from .state_votes import votes


def state_crosswalk(db: sqlite3.Connection, policy: Row) -> dict[str, Row]:
    # Independent identity-name match against GeoNames ADM1, never infer ISO
    # codes from a numeric GeoNames code. PH province parents use ADM1 region.
    admins: dict[str, set[str]] = {}
    for code, data in db.execute("SELECT admin1,data FROM geonames WHERE code='ADM1'"):
        row = unpack(data)
        names = [
            row["name"],
            row["name_en"],
            *json.loads(row["provenance"])
            .get("alternate_names_untyped", "")
            .split(","),
        ]
        for name in names:
            if key(name):
                admins.setdefault(key(name), set()).add(code)
    result: dict[str, Row] = {}
    for identity, data in db.execute("SELECT id,data FROM entities WHERE role='state'"):
        row = unpack(data)
        code = row["geonames_admin1"]
        method = "linked GeoNames administrative identity" if code else None
        if not code:
            matches = admins.get(key(row["name"]), set()) | admins.get(
                key(row["local_name"]), set()
            )
            if len(matches) == 1:
                code = next(iter(matches))
                method = "unique ADM1 name"
        if not code:
            # A province-equivalent state retains its source's region code.
            for source in row["source_ids"]:
                found = db.execute(
                    "SELECT data FROM divisions WHERE id=?", (source["id"],)
                ).fetchone()
                if not found:
                    continue
                point = unpack(found[0])
                parent = db.execute(
                    "SELECT g.admin1 FROM divisions d JOIN geonames g ON g.id=d.link "
                    "WHERE d.id=? AND g.code='ADM1'",
                    (point["parent_source_id"],),
                ).fetchone()
                if parent:
                    code, method = parent[0], "province parent ADM1 identity"
                else:
                    parent_row = db.execute(
                        "SELECT data FROM divisions WHERE id=?",
                        (point["parent_source_id"],),
                    ).fetchone()
                    if parent_row:
                        parent_place = unpack(parent_row[0])
                        matches = admins.get(
                            key(parent_place["name"]), set()
                        ) | admins.get(key(parent_place["name_en"]), set())
                        if len(matches) == 1:
                            code, method = (
                                next(iter(matches)),
                                "unique parent ADM1 alias",
                            )
        result[identity] = {"geonames_admin1": code, "method": method}
        if not code:
            result[identity] = votes(db, identity, policy)
    return result

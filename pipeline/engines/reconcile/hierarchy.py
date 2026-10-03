"""State crosswalks and canonical parent assignment, without inventing codes."""

from __future__ import annotations

import sqlite3

from .common import Row, pack, unpack
from .spatial import containing
from .state_codes import state_crosswalk


def attach_parents(
    db: sqlite3.Connection,
    policy: Row,
    batch_rows: int,
) -> None:
    crosswalk = state_crosswalk(db, policy, batch_rows)
    by_code: dict[str, list[str]] = {}
    for identity, match in crosswalk.items():
        code = match["geonames_admin1"]
        if code:
            by_code.setdefault(code, []).append(identity)
    # Store the crosswalk as data in the canonical artifact, with its evidence.
    db.execute("CREATE TABLE state_codes(entity TEXT PRIMARY KEY, data BLOB)")
    for identity, match in crosswalk.items():
        db.execute("INSERT INTO state_codes VALUES(?,?)", (identity, pack(match)))
    for identity, data in db.execute(
        "SELECT id,data FROM entities WHERE role IN ('city','district')"
    ):
        row: Row = unpack(data)
        options = by_code.get(row["geonames_admin1"], [])
        selected = options[0] if len(options) == 1 else None
        method = "GeoNames ADM1 identity crosswalk" if selected else None
        if len(options) > 1 and row["geonames_id"]:
            point = db.execute(
                "SELECT x,y FROM geonames WHERE id=?", (row["geonames_id"],)
            ).fetchone()
            if point:
                candidates = sorted(
                    {r[0] for r in containing(db, point[0], point[1], "state")}
                )
                if len(candidates) == 1:
                    selected, method = candidates[0], "city anchor in state area"
        if selected:
            row["parent"] = selected
            row["parent_method"] = method
            db.execute("UPDATE entities SET data=? WHERE id=?", (pack(row), identity))

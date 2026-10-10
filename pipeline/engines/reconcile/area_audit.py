"""Expose linked cities whose anchor lies outside their assigned area."""

from __future__ import annotations

import sqlite3

import shapely

from pipeline.engines.store.codec import Row, unpack

from .spatial import decode


def anchor_audit(db: sqlite3.Connection) -> Row:
    checked = 0
    outside: list[Row] = []
    for identity, data in db.execute(
        "SELECT DISTINCT e.id,e.data FROM areas a JOIN entities e ON e.id=a.entity "
        "WHERE a.role='city'"
    ):
        entity = unpack(data)
        anchor = db.execute(
            "SELECT x,y FROM geonames WHERE id=?", (entity["geonames_id"],)
        ).fetchone()
        if not anchor:
            continue
        checked += 1
        point = shapely.Point(*anchor)
        covered = any(
            decode(wkb).covers(point)
            for (wkb,) in db.execute(
                "SELECT geometry FROM areas WHERE entity=? AND role='city'", (identity,)
            )
        )
        if not covered:
            outside.append(
                {
                    "id": identity,
                    "name": entity["name"],
                    "geonames_id": entity["geonames_id"],
                    "population": entity["population"],
                    "link": entity["link"],
                }
            )
    outside.sort(key=lambda r: (-(r["population"] or 0), r["id"]))
    return {
        "checked": checked,
        "outside_count": len(outside),
        "outside": outside,
        "interpretation": (
            "An outside anchor can mean a displaced point, incomplete "
            "polygon, or an incorrect link; retained for review, "
            "not silently expanded."
        ),
    }

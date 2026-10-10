"""Explicit country semantics selected by source attributes, never coordinates."""

from __future__ import annotations

import json
import sqlite3

from pipeline.engines.store.codec import Row, unpack

from .entities import make_entity
from .matching import division


def targets(db: sqlite3.Connection, country: str, policy: Row) -> list[tuple[Row, Row]]:
    result = []
    for rule in policy["rollups"]:
        if rule["country"] != country:
            continue
        matches = []
        for source_id, data in db.execute(
            "SELECT id,data FROM divisions WHERE subtype='locality'"
        ):
            row = unpack(data)
            upstream = json.loads(row["provenance"])["upstream"]
            if upstream.get("wikidata") == rule["target_wikidata"]:
                point, match, link = division(db, source_id)
                if point and match:
                    matches.append(
                        make_entity(point, "city", country, policy, match, link)
                    )
        if len(matches) != 1:
            raise ValueError(f"Roll-up target is not a unique linked city: {rule}")
        result.append((rule, matches[0]))
    return result


def selected(row: Row, rules: list[tuple[Row, Row]]) -> Row | None:
    for rule, entity in rules:
        if row["subtype"] != rule["subtype"]:
            continue
        if row["entity_id"] in rule.get("entity_ids", []):
            return entity
        if (
            row["subdivision_code"] == rule.get("region_code")
            and "local_name_suffix" in rule
            and (row["name"] or "").endswith(rule["local_name_suffix"])
        ):
            return entity
    return None

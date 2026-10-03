"""City footprints supported by identical source identities across hierarchy roles."""

from __future__ import annotations

import json
import sqlite3

from .classification import trusted_city
from .common import Row, unpack
from .entities import make_entity
from .matching import division


def footprints(db: sqlite3.Connection, country: str, policy: Row) -> dict[str, Row]:
    """Exact shared Wikidata city identity, never a region's seat or similar name."""
    by_qid: dict[str, dict[str, Row]] = {}
    for identity, data in db.execute(
        "SELECT id,data FROM divisions WHERE subtype='locality' AND link IS NOT NULL"
    ):
        row = unpack(data)
        if row.get("feature_class") not in policy["region_city_classes"]:
            continue
        qid = json.loads(row["provenance"]).get("upstream", {}).get("wikidata")
        if not qid:
            continue
        point, match, link = division(db, identity)
        if (
            point
            and match
            and link.get("method") == "wikidata"
            and trusted_city(point, match, link, policy)
        ):
            value = make_entity(point, "city", country, policy, match, link)
            by_qid.setdefault(qid, {})[value["id"]] = value
    result = {}
    for identity, data in db.execute(
        "SELECT id,data FROM divisions WHERE subtype='region'"
    ):
        row = unpack(data)
        qid = json.loads(row["provenance"]).get("upstream", {}).get("wikidata")
        choices = by_qid.get(qid, {})
        if len(choices) == 1:
            result[identity] = next(iter(choices.values()))
    return result

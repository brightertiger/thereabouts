"""Resolve explicit settlement classifications without admitting neighborhoods."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .common import Row, unpack

# Shared by the scalar and vector oracles. These describe the stored priorities,
# not the evaluation sample or particular cities.
MUNICIPALITY_PRIORITY = 20
REGION_CITY_PRIORITY = 15
LINKED_LOCALITY_PRIORITY = 10
PROMOTED_ADMIN_PRIORITY = -10
POLICY_ROLLUP_PRIORITY = 50
CITY_STATE_PRIORITY = 100


def trusted_city(row: Row, match: Row | None, link: Row, policy: Row) -> bool:
    if row["subtype"] in policy["excluded_subtypes"]:
        return False
    if match is None:
        return bool(
            row["subtype"] == "locality"
            and row.get("feature_class") in policy["settlement_classes"]
        )
    if match["feature_code"] in policy["settlement_codes"]:
        return True
    if (
        match["feature_code"] == "PPLX"
        and row["subtype"] == "locality"
        and row.get("feature_class") in policy["trusted_city_classes"]
        and link["method"] == "wikidata"
    ):
        link["classification_conflict"] = (
            "GeoNames PPLX; shared Wikidata identity and explicit Overture city class"
        )
        return True
    return False


def dominated_localities(db: sqlite3.Connection, policy: Row) -> set[str]:
    """An administrative container is not its much larger nested city marker.

    Overture hierarchies describe containment, including point-in-ward relations.
    Never roll a city into that ward, or assign a whole district to its seat.
    Explicitly classified, linked municipalities keep their own footprints.
    """
    result: set[str] = set()
    for data, population in db.execute(
        "SELECT d.data,g.population FROM divisions d JOIN geonames g ON g.id=d.link "
        "WHERE d.subtype='locality' AND g.class='P' AND g.population>=?",
        (policy["hierarchy_city_minimum"],),
    ):
        row = unpack(data)
        if row.get("feature_class") not in policy["hierarchy_city_classes"]:
            continue
        upstream = json.loads(row["provenance"]).get("upstream", {})
        ancestors = {
            node["division_id"]
            for chain in upstream.get("hierarchies") or []
            for node in chain
            if node["subtype"] == "locality" and node["division_id"] != row["source_id"]
        }
        for identity in ancestors:
            found = db.execute(
                "SELECT d.data,d.link,g.population FROM divisions d "
                "LEFT JOIN geonames g ON g.id=d.link WHERE d.id=?",
                (identity,),
            ).fetchone()
            if not found:
                continue
            parent = unpack(found[0])
            if found[1] and parent.get("feature_class") in policy["settlement_classes"]:
                continue
            parent_population = found[2] if found[1] else parent.get("population")
            if (
                population
                >= max(1, parent_population or 0) * policy["hierarchy_population_ratio"]
            ):
                result.add(identity)
    return result


def area_priority(row: Row, match: Row | None, link: Row, policy: Row) -> int | None:
    """Require settlement evidence; keep administrative footprints separately."""
    if not trusted_city(row, match, link, policy):
        return None
    if row["subtype"] != "locality":
        return PROMOTED_ADMIN_PRIORITY if link.get("method") == "wikidata" else None
    if match and row.get("feature_class") in policy["settlement_classes"]:
        return MUNICIPALITY_PRIORITY
    return LINKED_LOCALITY_PRIORITY if match else 0


def city_order(entity: Row, priority: int, area: float) -> tuple[Any, ...]:
    """Specific linked municipalities win; unclassified overlaps use population."""
    population = (entity.get("population") or 0) if entity.get("geonames_id") else 0
    return (
        -priority,
        area if priority == MUNICIPALITY_PRIORITY else -population,
        -population if priority == MUNICIPALITY_PRIORITY else area,
        entity["id"],
    )

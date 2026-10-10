"""Absorption eligibility from settlement evidence, never administrative rank alone."""

import json
import sqlite3
from collections import Counter, defaultdict
from typing import cast

import shapely

from pipeline.engines.store.areas import entity_areas
from pipeline.engines.store.catalog import divisions as store_divisions
from pipeline.engines.store.catalog import geonames_place, geonames_point
from pipeline.engines.store.codec import Row
from pipeline.engines.store.entities import entities_in_roles, entity_point


def divisions(db: sqlite3.Connection) -> dict[str, Row]:
    result = {}
    for identity, link, row in store_divisions(db):
        upstream = json.loads(row["provenance"])["upstream"]
        result[identity] = {
            "id": identity,
            "link": link,
            "class": row.get("feature_class"),
            "subtype": row.get("subtype"),
            "name": row.get("name"),
            "local_type": upstream.get("local_type"),
            "parent": row.get("parent_source_id"),
            "longitude": row.get("longitude"),
            "latitude": row.get("latitude"),
        }
    return result


def eligible(
    code: str, population: int, classes: set[str], protected: bool, settings: Row
) -> str | None:
    if protected:
        return "linked city overrides section code"
    if code in settings["excluded_codes"]:
        return None
    typed = bool(classes & {"city", "town"})
    if population >= settings["minimum_population"]:
        return "population and active settlement"
    if code in settings["major_seats"]:
        return "national or first-order seat"
    if typed and (
        code in settings["seat_codes"] or population >= settings["typed_minimum"]
    ):
        return "typed town/city and seat or population"
    return None


def candidates(
    db: sqlite3.Connection, cc: str, settings: Row, rules: Row, evidence: dict[str, Row]
) -> tuple[dict[str, Row], Row]:
    linked: dict[str, list[Row]] = defaultdict(list)
    for row in evidence.values():
        if row["link"]:
            linked[row["link"]].append(row)
    output = {}
    counts: Counter[str] = Counter()
    forced = {r["city_id"] for r in rules.get("footprints", [])}
    forced.update(rules.get("independent", []))
    for identity, _, value in entities_in_roles(db, ("city",)):
        entity = cast(Row, value)
        gid = entity.get("geonames_id")
        ds = (
            linked.get(gid, [])
            if gid
            else [
                evidence[s["id"]] for s in entity["source_ids"] if s["id"] in evidence
            ]
        )
        classes = {r["class"] for r in ds if r["subtype"] == "locality" and r["class"]}
        code, pop = entity.get("feature_code") or "", entity.get("population") or 0
        protected = bool((entity.get("link") or {}).get("classification_conflict"))
        reason = eligible(code, pop, classes, protected, settings)
        if identity in forced or identity.startswith("city:country:"):
            reason = "explicit country policy"
        if not reason:
            if code in settings["seat_codes"]:
                counts["weak_seats_without_absorption"] += 1
            continue
        point = geonames_point(db, gid)
        if point is None:
            point = entity_point(db, identity)
        if point is None and reason == "explicit country policy":
            area = next(entity_areas(db, identity, "city"), None)
            if area:
                shape = shapely.from_wkb(area[1])
                if shape is None:
                    raise ValueError("City policy area has null geometry")
                anchor = shape.representative_point()
                point = (anchor.x, anchor.y)
        if point is None:
            counts["candidate_without_anchor"] += 1
            continue
        # GeoNames city names avoid accidentally selecting a linked village label.
        place = geonames_place(db, gid)
        name = (
            entity["name"] if classes & {"city", "town"} or not place else place["name"]
        )
        output[identity] = {
            "city_id": identity,
            "place_id": identity,
            "country_code": cc,
            "kind": "city" if "city" in classes or pop >= 100000 else "town",
            "name": name,
            "name_en": entity["name"]
            if entity["name_provenance"].get("language") == "en"
            else None,
            "latitude": point[1],
            "longitude": point[0],
            "population": pop,
            "source_ids": entity["source_ids"],
            "eligibility": reason,
            "classes": sorted(classes),
            "feature_code": code,
        }
        counts[reason] += 1
    return output, dict(counts)

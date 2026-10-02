"""Absorption eligibility from settlement evidence, never administrative rank alone."""

import json
import sqlite3
from collections import Counter, defaultdict

import shapely

from build_data.reconcile.common import Row, unpack


def divisions(db: sqlite3.Connection) -> dict[str, Row]:
    result = {}
    for identity, link, blob in db.execute("SELECT id,link,data FROM divisions"):
        row = unpack(blob)
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
    for identity, blob in db.execute("SELECT id,data FROM entities WHERE role='city'"):
        entity = unpack(blob)
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
        point = db.execute("SELECT x,y FROM geonames WHERE id=?", (gid,)).fetchone()
        if point is None:
            point = db.execute(
                "SELECT x,y FROM points WHERE entity=? ORDER BY id LIMIT 1", (identity,)
            ).fetchone()
        if point is None and reason == "explicit country policy":
            area = db.execute(
                "SELECT geometry FROM areas WHERE entity=? AND role='city' LIMIT 1",
                (identity,),
            ).fetchone()
            if area:
                shape = shapely.from_wkb(area[0])
                assert shape is not None
                anchor = shape.representative_point()
                point = (anchor.x, anchor.y)
        if point is None:
            counts["candidate_without_anchor"] += 1
            continue
        # GeoNames city names avoid accidentally selecting a linked village label.
        raw = db.execute("SELECT data FROM geonames WHERE id=?", (gid,)).fetchone()
        name = (
            entity["name"]
            if classes & {"city", "town"} or not raw
            else unpack(raw[0])["name"]
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

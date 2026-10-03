"""Measured per-country reports and an explicit pilot-to-world gate."""

from __future__ import annotations

import json

from pipeline.engines.artifacts import EVALUATION

from .area_audit import anchor_audit
from .audit import compact, large_places
from .classification import trusted_city
from .common import Row, unpack
from .coverage import land_coverage, place_coverage
from .lookup import Locator


def link_rates(oracle: Locator, country: str) -> Row:
    db = oracle.countries[country]
    groups = [
        {"subtype": k, "method": m, "count": n}
        for k, m, n in db.execute(
            "SELECT subtype,method,count(*) FROM divisions "
            "GROUP BY subtype,method ORDER BY 1,2"
        )
    ]
    total = sum(r["count"] for r in groups)
    linked = sum(r["count"] for r in groups if r["method"] != "unlinked")
    gn_q = db.execute("SELECT count(DISTINCT id) FROM wikidata").fetchone()[0]
    ov_q = sum(
        bool(json.loads(unpack(data)["provenance"]).get("upstream", {}).get("wikidata"))
        for (data,) in db.execute("SELECT data FROM divisions")
    )
    conflicts = []
    for source_id, data, match_data, method in db.execute(
        "SELECT d.id,d.data,g.data,d.method FROM divisions d "
        "JOIN geonames g ON g.id=d.link WHERE g.code='PPLX' ORDER BY d.id"
    ):
        row, match, link = unpack(data), unpack(match_data), {"method": method}
        if trusted_city(row, match, link, oracle.policy):
            conflicts.append(
                {
                    "overture": source_id,
                    "geonames": match["source_id"],
                    "name": row["name_en"] or row["name"],
                    "reason": link.get("classification_conflict"),
                }
            )
    area_ids = set()
    area_linked = set()
    for (data,) in db.execute("SELECT evidence FROM areas WHERE role='city'"):
        row = unpack(data)
        if row["source"] == "overture":
            identity = row["entity_id"]
            area_ids.add(identity)
            result = db.execute(
                "SELECT link FROM divisions WHERE id=?", (identity,)
            ).fetchone()
            if result and result[0]:
                area_linked.add(identity)
    return {
        "division_total": total,
        "division_linked": linked,
        "division_percent": 100 * linked / total if total else None,
        "by_subtype_and_method": groups,
        "geonames_with_wikidata": gn_q,
        "overture_wikidata_field_present": ov_q,
        "city_area_entities": len(area_ids),
        "city_area_entities_linked": len(area_linked),
        "city_area_percent": 100 * len(area_linked) / len(area_ids)
        if area_ids
        else None,
        "issues": db.execute(
            "SELECT count(*) FROM divisions WHERE issue IS NOT NULL"
        ).fetchone()[0],
        "classification_conflicts": conflicts,
    }


def named_points(oracle: Locator) -> list[Row]:
    fixtures = json.loads((EVALUATION / "reconcile/fixtures.json").read_text())
    result = []
    for label, lat, lon, cc, city, state in fixtures:
        if cc not in oracle.countries:
            continue
        answer = compact(oracle.locate(lat, lon))
        state_ok = (
            state == "*"
            or answer["state"] == state
            or (isinstance(state, list) and answer["state"] in state)
        )
        result.append(
            {
                "label": label,
                "lat": lat,
                "lon": lon,
                "answer": answer,
                "passed": answer["country_code"] == cc
                and answer["city"] == city
                and state_ok,
            }
        )
    return result


def country_report(oracle: Locator, country: str, policy: Row) -> Row:
    db = oracle.countries[country]
    return {
        "country": country,
        "state_policy": json.loads(
            db.execute("SELECT data FROM metadata WHERE key='state_policy'").fetchone()[
                0
            ]
        ),
        "links": link_rates(oracle, country),
        "large_places": large_places(oracle, country, policy),
        "linked_city_anchors": anchor_audit(db),
        "city_place_coverage": place_coverage(db),
        "city_land_coverage": land_coverage(db, oracle.land),
        "open_problems": [
            "Population ranking can select a broad municipality "
            "over a distinct nested settlement.",
            "Unlinked locality polygons have no validated "
            "GeoNames population/feature code.",
            "Containing-other city agreement is a geometric metric, "
            "not independent identity validation.",
        ],
    }

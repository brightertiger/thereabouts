"""Cross-source state codes and large-place self-lookups (no oracle tuning)."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter

from .common import Row, key, unpack
from .lookup import Locator
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


def compact(answer: Row) -> Row:
    return {
        "eligible": answer["eligible"],
        "country": (answer["country"] or {}).get("name"),
        "country_code": (answer["country"] or {}).get("country_code"),
        "state": (answer["state"] or {}).get("name"),
        "state_code": (answer["state"] or {}).get("code"),
        "city": (answer["city"] or {}).get("name"),
        "city_id": (answer["city"] or {}).get("id"),
        "city_geonames_id": (answer["city"] or {}).get("geonames_id"),
        "city_method": answer["city_method"],
        "land_method": answer["land_method"],
        "sovereign": answer["sovereign"],
    }


def large_places(oracle: Locator, country: str, policy: Row) -> Row:
    db = oracle.countries[country]
    crosswalk = state_crosswalk(db, policy)
    counts: Counter[str] = Counter()
    failures: list[Row] = []
    for (data,) in db.execute(
        "SELECT data FROM geonames WHERE class='P' AND population>=? "
        "ORDER BY population DESC,id",
        (policy["minimum_population"],),
    ):
        place = unpack(data)
        answer = oracle.locate(place["latitude"], place["longitude"])
        counts["total"] += 1
        present = bool(answer["country"])
        country_ok = present and answer["country"]["country_code"] == country
        counts["answer"] += present
        counts["country_agrees"] += country_ok
        state = answer["state"]
        state_code = (
            crosswalk.get(state["id"], {}).get("geonames_admin1") if state else None
        )
        state_applicable = country not in policy["no_state"] and bool(
            place["admin1_code"]
        )
        counts["state_applicable"] += state_applicable
        state_ok = state_applicable and state_code == place["admin1_code"]
        counts["state_agrees"] += state_ok
        counts["state_unmapped"] += state_applicable and state_code is None
        city = answer["city"]
        same = bool(city and city["geonames_id"] == place["source_id"])
        containing = bool(city and answer["city_method"] == "area" and country_ok)
        counts["city_same_identity"] += same
        counts["city_containing_other"] += containing and not same
        counts["city_same_or_containing"] += same or containing
        counts["city_present"] += bool(city)
        if (
            not country_ok
            or (state_applicable and not state_ok)
            or not (same or containing)
        ):
            failures.append(
                {
                    "id": place["source_id"],
                    "name": place["name"],
                    "population": place["population"],
                    "lat": place["latitude"],
                    "lon": place["longitude"],
                    "feature_code": place["feature_code"],
                    "expected_admin1": place["admin1_code"],
                    "actual_admin1": state_code,
                    "answer": compact(answer),
                    "country_ok": country_ok,
                    "state_ok": not state_applicable or state_ok,
                    "city_ok": same or containing,
                }
            )
    percentages = {
        name: 100 * counts[name] / counts["total"] if counts["total"] else None
        for name in (
            "answer",
            "country_agrees",
            "city_present",
            "city_same_identity",
            "city_same_or_containing",
        )
    }
    percentages["state_agrees"] = (
        100 * counts["state_agrees"] / counts["state_applicable"]
        if counts["state_applicable"]
        else None
    )
    return {
        "counts": dict(counts),
        "percentages": percentages,
        "failures": failures,
        "state_crosswalk": crosswalk,
        "city_metric_limit": (
            "Containing-other measures geometric inclusion, not independently "
            "adjudicated municipal identity. PPLX/historical P records stay in "
            "the denominator."
        ),
    }

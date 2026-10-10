"""Cross-source state codes and large-place self-lookups (no oracle tuning)."""

from __future__ import annotations

from collections import Counter

from pipeline.engines.store.codec import Row, unpack

from .evaluation import compare
from .lookup import Locator


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
    crosswalk = {
        identity: unpack(data)
        for identity, data in db.execute("SELECT entity,data FROM state_codes")
    }
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
        state = answer["state"]
        state_code = (
            crosswalk.get(state["id"], {}).get("geonames_admin1") if state else None
        )
        city = answer["city"]
        measures, checks = compare(
            place,
            country,
            (answer["country"] or {}).get("id"),
            (city or {}).get("geonames_id"),
            bool(city),
            answer["city_method"],
            state_code,
            policy,
        )
        counts.update(measures)
        if not all(checks.values()):
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
                    **checks,
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

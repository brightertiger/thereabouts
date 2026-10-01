"""Named points and every large settlement evaluated through stored ancestors."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import h3

from build_data.reconcile.common import Row, connect, unpack
from build_data.reconcile.lookup import entity

from .inputs import Inputs
from .reader import Cells


def named(reader: Cells, inputs: Inputs) -> list[Row]:
    fixtures = json.loads(
        (Path(__file__).parents[1] / "reconcile" / "fixtures.json").read_text()
    )
    output = []
    for label, lat, lon, cc, city, state in fixtures:
        cell = h3.latlng_to_cell(lat, lon, 8)
        answer = reader.lookup(cell)
        names: Row = {}
        code = (answer.get("country_id") or "").removeprefix("country:")
        if code in inputs.paths:
            db = connect(inputs.paths[code], readonly=True)
            try:
                for field in ("country", "state", "city"):
                    identity = answer.get(f"{field}_id")
                    names[field] = entity(db, identity)["name"] if identity else None
            finally:
                db.close()
        state_ok = (
            state == "*"
            or names.get("state") == state
            or (isinstance(state, list) and names.get("state") in state)
        )
        output.append(
            {
                "label": label,
                "latitude": lat,
                "longitude": lon,
                "h3": cell,
                "answer": {**answer, **names},
                "passed": code == cc and names.get("city") == city and state_ok,
                "pending": answer["cell_status"] == "pending",
            }
        )
    return output


def settlements(reader: Cells, inputs: Inputs, country: str) -> Row:
    db = connect(inputs.paths[country], readonly=True)
    counts: Counter[str] = Counter()
    failures = []
    try:
        codes = {
            identity: unpack(data)["geonames_admin1"]
            for identity, data in db.execute("SELECT entity,data FROM state_codes")
        }
        for (data,) in db.execute(
            "SELECT data FROM geonames WHERE class='P' AND population>=? "
            "ORDER BY population DESC,id",
            (inputs.policy["minimum_population"],),
        ):
            place = unpack(data)
            cell = h3.latlng_to_cell(place["latitude"], place["longitude"], 8)
            answer = reader.lookup(cell)
            counts["total"] += 1
            if answer["cell_status"] == "pending":
                counts["pending"] += 1
                continue
            counts["evaluated"] += 1
            country_ok = answer.get("country_id") == f"country:{country}"
            counts["answer"] += bool(answer.get("country_id"))
            counts["country_agrees"] += country_ok
            state_applicable = country not in inputs.policy["no_state"] and bool(
                place["admin1_code"]
            )
            state_code = codes.get(answer.get("state_id"))
            state_ok = state_applicable and state_code == place["admin1_code"]
            counts["state_applicable"] += state_applicable
            counts["state_agrees"] += state_ok
            counts["state_unmapped"] += state_applicable and state_code is None
            city_id = answer.get("city_id")
            city = entity(db, city_id) if city_id and country_ok else None
            same = bool(city and city.get("geonames_id") == place["source_id"])
            containing = bool(city and country_ok and answer["city_method"] == "area")
            counts["city_present"] += bool(city_id)
            counts["city_same_identity"] += same
            counts["city_containing_other"] += containing and not same
            counts["city_same_or_containing"] += same or containing
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
                        "feature_code": place["feature_code"],
                        "latitude": place["latitude"],
                        "longitude": place["longitude"],
                        "h3": cell,
                        "expected_admin1": place["admin1_code"],
                        "actual_admin1": state_code,
                        "answer": answer,
                        "country_ok": country_ok,
                        "state_ok": not state_applicable or state_ok,
                        "city_ok": same or containing,
                    }
                )
    finally:
        db.close()
    return {"country": country, "counts": dict(counts), "failures": failures}


def evaluate(cells: list[Row], inputs: Inputs) -> Row:
    reader = Cells(cells)
    countries = {}
    totals: Counter[str] = Counter()
    for cc in sorted(inputs.countries):
        report = settlements(reader, inputs, cc)
        countries[cc] = report
        totals.update(report["counts"])
    return {
        "named": named(reader, inputs),
        "settlements": countries,
        "settlement_counts": dict(totals),
        "definition": "Every GeoNames class P record at population >=15000; "
        "original points snap to r8 centres. Pending blocks remain in total and "
        "are reported separately. Containing-other measures assigned area at "
        "the cell centre, not independently adjudicated municipal identity.",
    }

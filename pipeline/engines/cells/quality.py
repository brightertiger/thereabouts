"""Named points and every large settlement evaluated through stored ancestors."""

from __future__ import annotations

import json
from collections import Counter

import h3

from pipeline.engines.artifacts import EVALUATION
from pipeline.engines.reconcile.common import Row, connect, unpack
from pipeline.engines.reconcile.evaluation import compare
from pipeline.engines.reconcile.lookup import entity

from .inputs import Inputs
from .reader import Cells, Reader


def display_names(inputs: Inputs, answer: Row) -> Row:
    cc = (answer.get("country_id") or "").removeprefix("country:")
    if cc not in inputs.paths:
        return {}
    db = connect(inputs.paths[cc], readonly=True)
    try:
        return {
            role: entity(db, answer[role + "_id"])["name"]
            if answer.get(role + "_id")
            else None
            for role in ("country", "state", "city")
        }
    finally:
        db.close()


def named(reader: Reader, inputs: Inputs) -> list[Row]:
    fixtures = json.loads((EVALUATION / "reconcile/fixtures.json").read_text())
    output = []
    for label, lat, lon, cc, city, state in fixtures:
        cell = h3.latlng_to_cell(lat, lon, 8)
        answer = reader.lookup(cell)
        names = display_names(inputs, answer)
        code = (answer.get("country_id") or "").removeprefix("country:")
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


def settlements(reader: Reader, inputs: Inputs, country: str) -> Row:
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
            state_code = codes.get(answer.get("state_id"))
            city_id = answer.get("city_id")
            city = entity(db, city_id) if city_id and country_ok else None
            measures, checks = compare(
                place,
                country,
                answer.get("country_id"),
                (city or {}).get("geonames_id"),
                bool(city_id),
                answer.get("city_method"),
                state_code,
                inputs.policy,
            )
            counts.update(measures)
            if not all(checks.values()):
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
                        **checks,
                    }
                )
    finally:
        db.close()
    return {"country": country, "counts": dict(counts), "failures": failures}


def probes(reader: Reader, inputs: Inputs) -> list[Row]:
    points = json.loads((EVALUATION / "cells/probes.json").read_text())
    output = []
    for label, lat, lon in points:
        cell = h3.latlng_to_cell(lat, lon, 8)
        answer = reader.lookup(cell)
        names = display_names(inputs, answer)
        output.append(
            {
                "label": label,
                "latitude": lat,
                "longitude": lon,
                "h3": cell,
                "answer": {**answer, **names},
            }
        )
    return output


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
        "probes": probes(reader, inputs),
        "settlements": countries,
        "settlement_counts": dict(totals),
        "definition": "Every GeoNames class P record at population >=15000; "
        "original points snap to r8 centres. Pending blocks remain in total and "
        "are reported separately. Containing-other measures assigned area at "
        "the cell centre, not independently adjudicated municipal identity.",
    }

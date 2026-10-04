"""Independently check the runtime against committed golden rows, entirely offline."""

import json
from pathlib import Path
from typing import Any

import h3

from thereabouts import Geocoder

FIXTURES = Path(__file__).resolve().parents[2] / "tests/fixtures"


def check() -> dict[str, Any]:
    extract = json.loads((FIXTURES / "core-source-extract.json").read_text())
    vectors = json.loads((FIXTURES / "core-sample-vectors.json").read_text())
    checked = 0
    matches = 0
    with Geocoder(FIXTURES / "packs/core-sample") as geo:
        for case in vectors["cases"]:
            request = case["request"]
            cell = (
                h3.latlng_to_cell(*request["values"], 8)
                if request["kind"] == "coordinates"
                else request["values"][0]
            )
            if h3.get_resolution(cell) != 8:
                continue
            result = (
                geo.reverse(
                    lat=request["values"][0], lon=request["values"][1], evidence=True
                )
                if request["kind"] == "coordinates"
                else geo.from_h3(cell, evidence=True)
            )
            source = extract["queries"][cell]
            row = source["cell"]
            assert result.evidence is not None, case["id"]
            if row is None:
                assert result.status == "not_found", case["id"]
                assert result.evidence.reason == (
                    "no_land" if source["block_present"] else "outside_coverage"
                )
                checked += 1
                continue
            stored = result.evidence.stored_cell
            assert stored is not None
            assert h3.get_resolution(stored) >= h3.get_resolution(row["h3"])
            assert h3.cell_to_parent(stored, h3.get_resolution(row["h3"])) == row["h3"]
            assert result.evidence.country_id == row["country_id"], case["id"]
            assert result.evidence.state_id == row["state_id"], case["id"]
            assert result.evidence.city_id == row["city_id"], case["id"]
            assert (result.city.id if result.city else None) == row["city_id"], case[
                "id"
            ]
            assert (
                "country:" + result.country.code if result.country else None
            ) == row["country_id"], case["id"]
            assigned = any(row[key] for key in ("country_id", "state_id", "city_id"))
            assert result.status == ("matched" if assigned else "not_found"), case["id"]
            expected = (
                {
                    "rural_nearest": "nearest",
                    "rural_nearest_distant": "nearest_distant",
                }.get(row["city_method"], "contained")
                if assigned
                else None
            )
            assert result.match == expected, case["id"]
            assert result.evidence.city_method == row["city_method"], case["id"]
            assert result.evidence.land_method == row["land_method"], case["id"]
            if row["state_id"]:
                assert result.state is not None
                state = extract["places"][row["state_id"]]
                state = next(
                    (
                        row
                        for row in extract["subdivisions"]
                        if row["code"] == state["code"]
                    ),
                    state,
                )
                assert result.state.code == state["code"]
                assert result.state.name == state["name"]
            zones = source["timezones"]
            if result.country:
                country = result.country.code
                zones = [
                    zone
                    for zone in zones
                    if any(
                        record["tzid"] == zone
                        and country in record["country_codes"].split(",")
                        for record in extract["zone_tables"]
                    )
                ]
            assert result.timezone == (zones[0] if len(zones) == 1 else None), case[
                "id"
            ]
            assert list(result.evidence.timezones) == (
                zones if len(zones) != 1 else []
            ), case["id"]
            checked += 1
            matches += assigned
    return {
        "checked_r8_requests": checked,
        "checked_r8_matches": matches,
        "golden_manifest_sha256": extract["source"]["golden_manifest_sha256"],
    }


if __name__ == "__main__":
    print(json.dumps(check()))

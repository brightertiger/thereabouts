"""Regenerate shared public results from the Python reference, without data export."""

import json
from pathlib import Path
from typing import Any

from h3.api import basic_int as h3

from thereabouts.client import Geocoder
from thereabouts.client_errors import InvalidInputError
from thereabouts.client_results import Resolution

FIXTURES = Path(__file__).parents[1] / "fixtures"
OUTPUT = FIXTURES / "conformance.json"


def resolve(geo: Geocoder, request: dict[str, Any]) -> Resolution:
    kind, values = request["kind"], request["values"]
    if kind == "coordinates":
        return geo.reverse(*values)
    if kind == "h3":
        return geo.from_h3(values[0])
    if kind == "postal":
        return geo.postal(values[0], country=request.get("country"))
    return geo.airport(
        values[0], country=request.get("country"), scheme=request.get("scheme")
    )


def requests() -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    root = h3.latlng_to_cell(12.97, 77.59, 3)
    branches = h3.cell_to_children(root, 4)
    cells = list(h3.cell_to_children(branches[0], 5)) + list(branches[1:])
    cells += [h3.cell_to_center_child(branches[4], 6)]
    cells += [h3.cell_to_center_child(branches[5], 7)]
    cells += list(h3.cell_to_children(branches[3], 8)[:2])
    cells += [h3.get_pentagons(8)[0], h3.latlng_to_cell(-89.99, 0, 8)]
    for cell in cells:
        result.append(
            (
                "serving",
                {"kind": "h3", "values": [f"{h3.cell_to_center_child(cell, 8):x}"]},
            )
        )
    for point in [
        (12.97, 77.59),
        (12.450873670161915, 77.77098085188615),
        (0, 180),
        (0, -180),
        (90, 0),
        (-90, 0),
        (52.37, 4.9),
    ]:
        result.append(("serving", {"kind": "coordinates", "values": point}))
    for country, value in [
        ("AA", "00100"),
        ("AA", "AMB"),
        ("IN", "560001"),
        ("AA", "VOID"),
        ("ca", " a1a 1a1 "),
        ("AA", "missing"),
    ]:
        result.append(
            ("codes/postal", {"kind": "postal", "values": [value], "country": country})
        )
    for scheme, code_value, source_country in [
        ("iata", "zzz", None),
        ("iata", "ZZZ", "AA"),
        ("iata", "ZZZ", "BB"),
        ("ident", "AA01", None),
        ("icao", "AAAA", None),
        ("gps", "GPS1", None),
        ("local", "L1", "AA"),
        ("local", "L1", "BB"),
        ("iata", "missing", None),
    ]:
        result.append(
            (
                "codes/airports",
                {
                    "kind": "airport",
                    "values": [code_value],
                    "scheme": scheme,
                    "country": source_country,
                },
            )
        )
    for values in [(True, 0), (91, 0), (0, 181), ("0", 0), (None, 0)]:
        result.append(("serving", {"kind": "coordinates", "values": values}))
    for invalid_cell in ["0" * 15, "836014fffffffff", " 8860145b49fffff", 42]:
        result.append(("serving", {"kind": "h3", "values": [invalid_cell]}))
    missing_context: list[tuple[str, dict[str, Any]]] = [
        ("codes/postal", {"kind": "postal", "values": ["00100"]}),
        ("codes/postal", {"kind": "postal", "values": [100], "country": "AA"}),
        ("codes/airports", {"kind": "airport", "values": ["ZZZ"]}),
        ("codes/airports", {"kind": "airport", "values": ["L1"], "scheme": "local"}),
    ]
    result.extend(missing_context)
    return result


def bundle() -> dict[str, Any]:
    cases = []
    for index, (fixture, request) in enumerate(requests()):
        case: dict[str, Any] = {
            "id": index,
            "pack": fixture,
            "request": json.loads(json.dumps(request)),
        }
        with Geocoder(FIXTURES / fixture, backend="python") as geo:
            try:
                case["result"] = resolve(geo, request).to_dict()
            except InvalidInputError as exc:
                case["error"] = {"name": type(exc).__name__, "message": str(exc)}
        cases.append(case)
    return {
        "schema": "thereabouts-conformance-1",
        "float_absolute_tolerance": 0,
        "cases": cases,
    }


if __name__ == "__main__":
    OUTPUT.write_text(
        json.dumps(bundle(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

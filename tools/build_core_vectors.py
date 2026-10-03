"""Freeze shared reverse vectors; legacy postal/airport vectors remain unchanged."""

import json
from pathlib import Path
from typing import Any

import h3

from tests.serve.fixtures import golden
from thereabouts import Geocoder, _core
from thereabouts.packs.address import cell_at

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def resolve(geo: Geocoder, request: dict[str, Any]) -> dict[str, Any]:
    if request["kind"] == "h3":
        return geo.from_h3(request["values"][0]).to_dict()
    return geo.reverse(lat=request["values"][0], lon=request["values"][1]).to_dict()


def synthetic() -> None:
    directory = FIXTURES / "datasets/core-synthetic"
    manifest, _ = golden(directory)
    pack = FIXTURES / "packs/core-synthetic"
    _core.write_pack(
        str(manifest.parent),
        "core",
        str(pack),
        {
            "data_version": "synthetic",
            "sources": ["synthetic"],
            "attribution": "Synthetic test data; public domain",
            "notices": {"LICENSE": "Synthetic fixture: public domain."},
        },
    )
    old = json.loads((FIXTURES / "conformance.json").read_text())
    cases = []
    with Geocoder(pack) as geo:
        for case in old["cases"]:
            if case["request"]["kind"] not in {"h3", "coordinates"}:
                continue
            result = resolve(geo, case["request"])
            # Assert independently retained legacy identities and method meaning.
            if "result" in case and case["result"]["selected"] is not None:
                previous = case["result"]["selected"]
                assert result["status"] == "matched"
                if previous["city"]:
                    assert result["city"]["id"] == previous["city"]["id"]
                if previous["country"]:
                    assert (
                        result["country"]["code"] == previous["country"]["country_code"]
                    )
                method = previous["methods"]["city"]
                expected = {
                    "rural_nearest": "nearest",
                    "rural_nearest_distant": "nearest_distant",
                }.get(method, "contained")
                assert result["match"] == expected
            cases.append(
                dict(id=f"legacy-{case['id']}", request=case["request"], result=result)
            )
    write_json(
        FIXTURES / "core-synthetic-vectors.json",
        {
            "schema": "thereabouts-conformance-2",
            "pack": "packs/core-synthetic",
            "cases": cases,
        },
    )


def real() -> None:
    import struct

    pack = FIXTURES / "packs/core-sample"
    requests: list[dict[str, Any]] = []
    for point in [
        (50.8503, 4.3517),
        (52.3676, 4.9041),
        (49.6116, 6.1319),
        (48.8566, 2.3522),
        (41.0082, 28.9784),
        (19.076, 72.8777),
        (28.6139, 77.209),
        (39.7817, -89.6501),
        (52.5, 3.5),  # North Sea within an inventoried sample block: no land.
        (0, 0),
        (90, 0),
        (-90, 0),
    ]:
        requests.extend(
            [
                dict(kind="coordinates", values=list(point)),
                dict(kind="h3", values=[h3.latlng_to_cell(*point, 8)]),
            ]
        )
    # Read only the documented binary directory to enumerate stored sample cells;
    # expected JSON comes from the API, with independent golden checks in pytest.
    cells: list[str] = []
    for path in sorted(pack.glob("cells-*.bin")):
        data = path.read_bytes()
        _, _, start, length, _ = struct.unpack_from("<IIQQQ", data, 32)
        _, _, keys, _, _ = struct.unpack_from("<IIQQQ", data, 64)
        for offset in range(start, start + length, 40):
            block, count, key_start, _, _, _, _ = struct.unpack_from(
                "<IIQIIQQ", data, offset
            )
            for i in range(count):
                key = struct.unpack_from("<H", data, keys + key_start + i * 2)[0]
                cells.append(f"{cell_at(block, key):x}")
    with Geocoder(pack) as geo:
        categories: set[str] = set()
        for cell in cells:
            result = geo.from_h3(cell)
            category = result.status + ":" + str(result.match)
            if category not in categories:
                categories.add(category)
                fine = h3.cell_to_center_child(cell, 8)
                requests.extend(
                    [
                        dict(kind="h3", values=[fine]),
                        dict(kind="coordinates", values=list(h3.cell_to_latlng(fine))),
                    ]
                )
        # Evenly spread through the stored keyspace, deterministic across runs.
        for i in range(48):
            cell = cells[i * (len(cells) - 1) // 47]
            fine = h3.cell_to_center_child(cell, 8)
            requests.append(dict(kind="h3", values=[fine]))
            requests.append(
                dict(kind="coordinates", values=list(h3.cell_to_latlng(fine)))
            )
        for resolution in range(9):
            requests.append(
                dict(kind="h3", values=[h3.latlng_to_cell(50.8503, 4.3517, resolution)])
            )
        cases: list[dict[str, Any]] = [
            dict(id=f"real-{i:03}", request=request, result=resolve(geo, request))
            for i, request in enumerate(requests)
        ]
    assert any(c["result"]["status"] == "ambiguous" for c in cases)
    assert any(c["result"]["match"] == "nearest_distant" for c in cases)
    write_json(
        FIXTURES / "core-sample-vectors.json",
        {
            "schema": "thereabouts-conformance-2",
            "pack": "packs/core-sample",
            "cases": cases,
        },
    )
    print(f"Frozen {len(cases)} real reverse vectors")


if __name__ == "__main__":
    synthetic()
    real()

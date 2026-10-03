"""Independently check frozen reverse identities against read-only golden rows."""

import json
from typing import Any

import h3
import pyarrow.parquet as pq

from tools.build_sample_pack import GOLDEN, ROOT, sha


def check() -> dict[str, Any]:
    manifest = json.loads((GOLDEN / "manifest.json").read_text())
    tables = {t["block"]: t for t in manifest["tables"] if t["kind"] == "cells"}
    cache: dict[str, dict[str, dict[str, Any]]] = {}
    vectors = json.loads((ROOT / "tests/fixtures/core-sample-vectors.json").read_text())
    checked = 0
    for case in vectors["cases"]:
        request, result = case["request"], case["result"]
        cell = (
            h3.latlng_to_cell(*request["values"], 8)
            if request["kind"] == "coordinates"
            else request["values"][0]
        )
        if h3.get_resolution(cell) != 8 or result["status"] not in {
            "matched",
            "ambiguous",
        }:
            continue
        block = h3.cell_to_parent(cell, 3)
        if block not in cache:
            table = tables[block]
            path = GOLDEN / manifest["data_root"] / table["path"]
            assert sha(path) == table["sha256"]
            rows = pq.read_table(
                path, columns=["h3", "country_id", "state_id", "city_id", "city_method"]
            ).to_pylist()
            cache[block] = {row["h3"]: row for row in rows}
        found = next(
            (
                cache[block][parent]
                for resolution in range(8, 2, -1)
                if (parent := h3.cell_to_parent(cell, resolution)) in cache[block]
            ),
            None,
        )
        assert found is not None, case["id"]
        assert (result["city"]["id"] if result["city"] else None) == found["city_id"], (
            case["id"]
        )
        assert (
            "country:" + result["country"]["code"] if result["country"] else None
        ) == found["country_id"], case["id"]
        expected = {
            "rural_nearest": "nearest",
            "rural_nearest_distant": "nearest_distant",
        }.get(found["city_method"], "contained")
        assert result["match"] == expected, case["id"]
        checked += 1
    return {
        "checked_r8_matches": checked,
        "golden_manifest_sha256": sha(GOLDEN / "manifest.json"),
    }


if __name__ == "__main__":
    print(json.dumps(check()))

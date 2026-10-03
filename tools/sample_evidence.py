"""Extract golden subset rows independently of the Rust core."""

import json
from pathlib import Path
from typing import Any

import h3
import pyarrow.parquet as pq


def extract(
    dataset: Path, vectors: Path, output: Path, provenance: dict[str, Any]
) -> None:
    """Freeze only the source rows needed to independently test the sample queries."""
    manifest = json.loads((dataset / "manifest.json").read_text())

    def rows(kind: str) -> list[dict[str, Any]]:
        return [
            row
            for table in manifest["tables"]
            if table["kind"] == kind
            for row in pq.read_table(dataset / table["path"]).to_pylist()
        ]

    cells = {row["h3"]: row for row in rows("cells")}
    blocks = {
        table["block"] for table in manifest["tables"] if table["kind"] == "cells"
    }
    places = {row["place_id"]: row for row in rows("places")}
    zones: dict[str, set[str]] = {}
    for row in rows("timezone_cells"):
        zones.setdefault(row["h3"], set()).add(row["tzid"])
    queries = {}
    identities: set[str] = set()
    for case in json.loads(vectors.read_text())["cases"]:
        request = case["request"]
        cell = (
            h3.latlng_to_cell(*request["values"], 8)
            if request["kind"] == "coordinates"
            else request["values"][0]
        )
        if h3.get_resolution(cell) != 8:
            continue
        found = next(
            (
                cells[parent]
                for r in range(8, 2, -1)
                if (parent := h3.cell_to_parent(cell, r)) in cells
            ),
            None,
        )
        source = None
        if found:
            source = {
                key: found[key]
                for key in (
                    "h3",
                    "country_id",
                    "state_id",
                    "city_id",
                    "city_method",
                    "land_method",
                )
            }
            identities.update(
                row[key] for key in ("country_id", "state_id", "city_id") if row[key]
            )
        zone_set = set().union(
            *(zones.get(h3.cell_to_parent(cell, r), set()) for r in range(9))
        )
        queries[cell] = {
            "cell": source,
            "block_present": h3.cell_to_parent(cell, 3) in blocks,
            "timezones": sorted(zone_set),
        }
    result = {
        "source": provenance,
        "queries": queries,
        "places": {
            key: {field: places[key][field] for field in ("place_id", "code", "name")}
            for key in sorted(identities)
        },
        "subdivisions": [
            {key: row.get(key) for key in ("code", "name")}
            for row in rows("subdivisions")
        ],
        "zone_tables": [
            {key: row[key] for key in ("tzid", "country_codes")}
            for row in rows("zone_tables")
        ],
    }
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )

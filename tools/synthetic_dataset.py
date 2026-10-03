"""Enrich the legacy spatial fixture with the core writer's required side tables."""

import json
from pathlib import Path

import h3
import pyarrow as pa
import pyarrow.parquet as pq

from tests.serve.fixtures import golden as spatial_golden
from tests.serve.fixtures import write_table
from thereabouts.packs.jsonio import sha256


def golden(root: Path) -> tuple[Path, Path]:
    """Keep legacy identities; add metadata and overlapping timezone rows."""
    manifest_path, release = spatial_golden(root)
    manifest = json.loads(manifest_path.read_text())
    places_path = root / "golden/places/AA.parquet"
    places = pq.read_table(places_path)
    rows = places.to_pylist()
    next(row for row in rows if row["role"] == "state")["code"] = "AA.A"
    pq.write_table(
        pa.Table.from_pylist(rows, schema=places.schema),
        places_path,
        compression="zstd",
    )
    table = next(t for t in manifest["tables"] if t["kind"] == "places")
    table.update(size=places_path.stat().st_size, sha256=sha256(places_path))
    schemas_rows = {
        "countries": (
            pa.schema(
                [
                    ("country_code", pa.string()),
                    ("alpha3", pa.string()),
                    ("name", pa.string()),
                ]
            ),
            [
                {
                    "country_code": "AA",
                    "alpha3": "AAA",
                    "name": "München 東京 country:AA",
                }
            ],
        ),
        "subdivisions": (
            pa.schema(
                [
                    ("code", pa.string()),
                    ("country_code", pa.string()),
                    ("name", pa.string()),
                ]
            ),
            [
                {
                    "code": "AA.A",
                    "country_code": "AA",
                    "name": "München 東京 state:synthetic:A",
                }
            ],
        ),
        "zone_tables": (
            pa.schema(
                [
                    ("tzid", pa.string()),
                    ("country_codes", pa.string()),
                    ("table", pa.string()),
                ]
            ),
            [
                {"tzid": "Fixture/One", "country_codes": "AA", "table": "zone.tab"},
                {"tzid": "Fixture/Two", "country_codes": "BB", "table": "zone.tab"},
            ],
        ),
        "timezone_cells": (
            pa.schema([("h3", pa.string()), ("tzid", pa.string())]),
            [
                {"h3": h3.latlng_to_cell(12.97, 77.59, 3), "tzid": zone}
                for zone in ("Fixture/One", "Fixture/Two")
            ],
        ),
    }
    for kind, (schema, records) in schemas_rows.items():
        manifest["tables"].append(
            write_table(
                root, f"golden/{kind}/sample.parquet", records, schema, kind=kind
            )
        )
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )
    return manifest_path, release

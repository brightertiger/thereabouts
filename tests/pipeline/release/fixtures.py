"""Small complete schemas with two blocks that coalesce into one cell file."""

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from h3.api import basic_int as h3

from pipeline.config import Config, load
from pipeline.files import file_record
from pipeline.release.dataset_schema import inputs
from pipeline.release.source import Snapshot, external
from pipeline.release.tables import schema_description
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.resources import ResourceGuard

# The cells' country and city, closed under the pack writer's reference rule.
CATALOGUE: dict[str, list[dict[str, Any]]] = {
    "places": [
        {"place_id": "country:MY", "role": "country", "country_code": "MY"},
        {
            "place_id": "city:one",
            "role": "city",
            "country_code": "MY",
            "parent_id": "country:MY",
            "normalized_city_id": "city:one",
            "name": "One",
        },
    ],
    "canonical_cities": [
        {
            "city_id": "city:one",
            "place_id": "city:one",
            "country_code": "MY",
            "kind": "city",
            "name": "One",
            "eligibility": "fixture",
            "latitude": 3.139,
            "longitude": 101.6869,
            "source_ids": "[]",
            "footprint_references": "[]",
            "allocation_rule": "fixture",
        }
    ],
    "place_to_city": [
        {"place_id": "city:one", "city_id": "city:one", "method": "self"}
    ],
}


def fixture(
    root: Path, *, closed: bool = True
) -> tuple[Snapshot, Config, ResourceGuard]:
    config = load()
    config.release.enabled = True
    config.release.version = "2026.10"
    config.release.packs.families = []
    config.release.dataset.batch_rows = 2
    config.content.chunk_rows = 2
    config.content.merge_fan_in = 2
    cell = h3.latlng_to_cell(3.139, 101.6869, 8)
    parent = h3.cell_to_parent(cell, 1)
    blocks = sorted(h3.cell_to_children(parent, 3))[:2]
    config.release.countries = ["MY"]
    config.release.blocks = [f"{block:x}" for block in blocks]
    source = root / "input"
    source.mkdir()
    tables = []
    descriptions = inputs(schema_description(REPOSITORY / config.release.schema))
    for kind, description in descriptions.items():
        fields = []
        for column in description["columns"]:
            typ = column["type"]
            arrow = (
                pa.list_(pa.field("element", pa.string()))
                if typ == "list<element: string>"
                else pa.type_for_alias(typ)
            )
            fields.append(pa.field(column["name"], arrow, nullable=column["nullable"]))
        schema = pa.schema(fields)
        values: list[dict[str, Any]] = []
        if kind == "cells":
            for block in blocks:
                key = h3.cell_to_center_child(block, 8)
                values.append(
                    {
                        "h3": f"{key:x}",
                        "h3_uint64": key,
                        "h3_resolution": 8,
                        "country_id": "country:MY",
                        "state_id": None,
                        "city_id": "city:one",
                        "city_method": "rural_nearest_distant",
                    }
                )
        elif kind in CATALOGUE and closed:
            values = CATALOGUE[kind]
        elif kind == "zone_tables":
            values = [
                {
                    "source": "timezones",
                    "source_id": "one",
                    "country_codes": "MY,SG",
                    "source_release": "test",
                    "license": "public-domain",
                    "provenance": "{}",
                }
            ]
        for number, rows in enumerate(
            [[row] for row in values] if kind == "cells" else [values]
        ):
            path = source / f"{kind}-{number}.parquet"
            table = pa.Table.from_pylist(rows, schema=schema)
            pq.write_table(table, path)
            entry = {**file_record(source, path), "kind": kind, "rows": len(rows)}
            if kind == "cells":
                entry["block"] = config.release.blocks[number]
            if kind in {"places", "canonical_cities", "place_to_city"}:
                entry["country"] = "MY"
            tables.append(entry)
    write_json(
        source / "manifest.json",
        {
            "completed": True,
            "data_root": ".",
            "tables": tables,
            "reference_resolution": 8,
            "block_resolution": 3,
            "normalization": {
                "completed": True,
                "policy": {"distant_m": 25000, "nearest_m": 50000},
            },
        },
    )
    return external(source, config.h3), config, ResourceGuard(root, config.resources)

"""A few logical blocks exercise every method without acquiring geographic data."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from h3.api import basic_int as h3

from pipeline.engines.cells.schemas import CELLS
from pipeline.engines.cities.schemas import CITIES, MAPPING
from pipeline.engines.serving.checkpoints import file_record
from pipeline.engines.serving.metadata import write_manifest
from pipeline.engines.serving.snapshot import (
    INTEGRITY,
    NORMALIZATION_INTEGRITY,
    PLACE_SCHEMA,
    Row,
)
from thereabouts.packs.jsonio import canonical
from thereabouts.packs.layout import CITY_METHODS


def place(identity: str, role: str, parent: str | None) -> Row:
    return {
        "place_id": identity,
        "role": role,
        "name": "München 東京 " + identity,
        "name_en": None,
        "local_name": "東京",
        "country_code": "AA",
        "code": "AA" if role == "country" else None,
        "code_status": None,
        "parent_id": parent,
        "parent_method": "source" if parent else None,
        "sovereign_id": "country:BB",
        "sovereign_code": "BB",
        "sovereign_name": None,
        "population": 0,
        "source_ids": '[{"source":"synthetic","id":"a"}]',
        "provenance": '{"source_release":"fixture"}',
        "name_provenance": '{"language":"ja"}',
        "link": "null",
        "overture_ids": [],
        "wikidata_ids": [],
        "normalized_city_id": identity
        if role in {"city", "town", "settlement"}
        else None,
        "normalization_method": "self" if role == "city" else "non-settlement",
        "settlement_kind": role,
    }


def cell(
    key: int, method: str | None = "city_polygon", *, unassigned: bool = False
) -> Row:
    return {
        "h3": h3.int_to_str(key),
        "h3_uint64": key,
        "h3_resolution": h3.get_resolution(key),
        "country_id": None if unassigned else "country:AA",
        "state_id": None if unassigned else "state:synthetic:A",
        "city_id": "city:synthetic:A" if method else None,
        "country_method": None if unassigned else "area",
        "state_method": None if unassigned else "area",
        "city_method": method,
        "land_method": "offshore" if method == "policy_polygon" else "land",
    }


def write_table(
    root: Path, name: str, rows: list[Row], schema: pa.Schema, **fields: object
) -> Row:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")
    return file_record(path, root, rows=len(rows), **fields)


def golden(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    places = [
        place("country:AA", "country", None),
        place("country:BB", "country", None),
        place("state:synthetic:A", "state", "country:AA"),
        place("district:synthetic:A", "district", "state:synthetic:A"),
        place("city:synthetic:A", "city", "district:synthetic:A"),
        place("city:synthetic:unused", "city", "state:synthetic:A"),
    ]
    places[1].update(country_code="BB", code="BB")
    tables = [
        write_table(
            root,
            "golden/places/AA.parquet",
            places,
            PLACE_SCHEMA,
            kind="places",
            country="AA",
        )
    ]
    tables.append(
        write_table(
            root,
            "golden/canonical_cities/AA.parquet",
            [
                {
                    "city_id": "city:synthetic:A",
                    "place_id": "city:synthetic:A",
                    "country_code": "AA",
                    "kind": "city",
                    "name": "München 東京",
                    "latitude": 12.97,
                    "longitude": 77.59,
                    "eligibility": "synthetic",
                    "source_ids": "[]",
                    "footprint_references": "[]",
                    "allocation_rule": "synthetic",
                    "population": None,
                }
            ],
            CITIES,
            kind="canonical_cities",
        )
    )
    tables.append(
        write_table(
            root,
            "golden/place_to_city/AA.parquet",
            [
                {
                    "place_id": r["place_id"],
                    "city_id": r["normalized_city_id"],
                    "method": r["normalization_method"],
                    "evidence": None,
                }
                for r in places
            ],
            MAPPING,
            kind="place_to_city",
        )
    )
    block = h3.latlng_to_cell(12.97, 77.59, 3)
    children = h3.cell_to_children(block, 4)
    cells = [
        cell(key, method)
        for key, method in zip(
            h3.cell_to_children(children[0], 5), CITY_METHODS[1:], strict=True
        )
    ]
    cells += [cell(children[1], None, unassigned=True), cell(children[2], None)]
    fine = h3.cell_to_children(children[3], 8)
    cells += [cell(key) for key in fine[:20]]
    # Retain levels 6 and 7 on disjoint branches too.
    cells += [
        cell(h3.cell_to_center_child(children[4], 6)),
        cell(h3.cell_to_center_child(children[5], 7)),
    ]
    blocks = {
        block: cells,
        h3.get_pentagons(3)[0]: [cell(h3.get_pentagons(3)[0])],
        h3.latlng_to_cell(0, 179.99, 3): [],
        h3.latlng_to_cell(-89.99, 0, 3): [cell(h3.latlng_to_cell(-89.99, 0, 3))],
    }
    for key, data in blocks.items():
        name = h3.int_to_str(key)
        tables.append(
            write_table(
                root,
                f"golden/cells/{name}.parquet",
                data,
                CELLS,
                kind="cells",
                block=name,
            )
        )
    quality = {
        "integrity": dict.fromkeys(INTEGRITY, 0),
        "normalization_integrity": dict.fromkeys(NORMALIZATION_INTEGRITY, 0),
        "failed_spatial_gates": {
            key: [] for key in ("footprints", "neighbours", "named", "all_boundaries")
        },
    }
    artifacts = []
    for name, artifact in (
        ("quality.json", canonical(quality)),
        ("DATA_LICENSES.md", b"Synthetic data only. Public domain.\n"),
        ("DATASET_CARD.md", b"Synthetic test blocks, not geographic evidence.\n"),
    ):
        path = root / "golden" / name
        path.write_bytes(artifact)
        artifacts.append(file_record(path, root))
    manifest = root / "golden/manifest.json"
    write_manifest(
        manifest,
        {
            "schema_version": "golden-2",
            "completed": True,
            "data_root": "..",
            "reference_resolution": 8,
            "block_resolution": 3,
            "tables": tables,
            "verification_artifacts": artifacts,
            "builder": "synthetic",
            "implementation": "synthetic",
            "normalization": {
                "completed": True,
                "policy": {
                    "town_radius": {"enabled": False},
                    "nearest_m": 50000,
                    "distant_m": 25000,
                },
            },
        },
    )
    notice = root / "LICENSE.txt"
    notice.write_text("Synthetic fixture: public domain.\n")
    release = root / "release.json"
    write_manifest(
        release,
        {
            "data_version": "synthetic",
            "catalogue_epoch": "synthetic",
            "sources": [
                {
                    "source": "synthetic",
                    "release": "fixture",
                    "license": "public-domain",
                    "attribution": "Thereabouts test fixture",
                    "source_url": "https://example.invalid/synthetic",
                    "license_url": "https://example.invalid/license",
                }
            ],
            "notices": [file_record(notice, root)],
        },
    )
    return manifest, release

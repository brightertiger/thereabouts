"""Export a geographically spread synthetic workload, with thousands of places."""

import argparse
from pathlib import Path

import numpy as np
from h3.api import basic_int as h3

from pipeline.engines.cells.schemas import CELLS
from pipeline.engines.cities.schemas import CITIES, MAPPING
from pipeline.engines.serving.export import export
from pipeline.engines.serving.metadata import write_manifest
from pipeline.engines.serving.snapshot import PLACE_SCHEMA, Row
from tests.serve.fixtures import cell, golden, place, write_table
from thereabouts.packs.jsonio import canonical, parse
from thereabouts.packs.layout import CITY_METHODS

# Geographic centres only; all identities, names and assignments are invented.
CENTRES = (
    (40.7, -74),
    (34.1, -118.2),
    (19.4, -99.1),
    (-23.5, -46.6),
    (-33.4, -70.7),
    (51.5, -0.1),
    (52.5, 13.4),
    (30.0, 31.2),
    (6.5, 3.4),
    (-26.2, 28.0),
    (28.6, 77.2),
    (1.3, 103.8),
    (35.7, 139.7),
    (39.9, 116.4),
    (-33.9, 151.2),
    (64.1, -21.9),
)
CITIES_PER_BLOCK = 64


def entity(identity: str, role: str, parent: str | None, country: str) -> Row:
    row = place(identity, role, parent)
    row.update(
        country_code=country,
        sovereign_id="country:" + country,
        sovereign_code=country,
        code=country if role == "country" else None,
        name=f"Synthetic {identity} — München 東京",
        name_en=None,
        source_ids=canonical([{"source": "synthetic", "id": identity}]).decode(),
    )
    return row


def create(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=False)
    manifest, release = golden(output / "input")
    root = release.parent
    value = parse(manifest.read_bytes())
    tables, places, points = [], [], []
    for region, (latitude, longitude) in enumerate(CENTRES):
        country = "A" + chr(ord("A") + region)
        country_id = "country:" + country
        places.append(entity(country_id, "country", None, country))
        blocks = sorted(h3.grid_disk(h3.latlng_to_cell(latitude, longitude, 3), 1))[:4]
        for number, block in enumerate(blocks):
            prefix = f"{region:02d}:{number}"
            state_id = "state:synthetic:" + prefix
            places.append(entity(state_id, "state", country_id, country))
            cities = [
                f"city:synthetic:{prefix}:{index:02d}"
                for index in range(CITIES_PER_BLOCK)
            ]
            places.extend(
                entity(identity, "city", state_id, country) for identity in cities
            )
            branches = h3.cell_to_children(block, 4)
            keys = list(h3.cell_to_children(branches[0], 5))
            keys += [
                child
                for branch in branches[1:]
                for child in h3.cell_to_children(branch, 8)[::3]
            ]
            rows = []
            for index, key in enumerate(keys):
                row = cell(key, CITY_METHODS[1 + (index // CITIES_PER_BLOCK) % 7])
                row.update(
                    country_id=country_id,
                    state_id=state_id,
                    city_id=cities[index % CITIES_PER_BLOCK],
                )
                rows.append(row)
                if index % 7 == 0:
                    fine = h3.cell_to_center_child(key, 8)
                    points.append(h3.cell_to_latlng(fine))
            tables.append(
                write_table(
                    root,
                    f"golden/cells/{block:x}.parquet",
                    rows,
                    CELLS,
                    kind="cells",
                    block=f"{block:x}",
                )
            )
    tables.append(
        write_table(
            root, "golden/places/sample.parquet", places, PLACE_SCHEMA, kind="places"
        )
    )
    canonical_cities = [
        {
            "city_id": row["place_id"],
            "place_id": row["place_id"],
            "country_code": row["country_code"],
            "kind": "city",
            "name": row["name"],
            "latitude": 0.0,
            "longitude": 0.0,
            "eligibility": "synthetic",
            "source_ids": row["source_ids"],
            "footprint_references": "[]",
            "allocation_rule": "synthetic",
            "population": None,
        }
        for row in places
        if row["role"] == "city"
    ]
    tables.append(
        write_table(
            root,
            "golden/canonical_cities/sample.parquet",
            canonical_cities,
            CITIES,
            kind="canonical_cities",
        )
    )
    mappings = [
        {
            "place_id": row["place_id"],
            "city_id": row["normalized_city_id"],
            "method": row["normalization_method"],
            "evidence": None,
        }
        for row in places
    ]
    tables.append(
        write_table(
            root,
            "golden/place_to_city/sample.parquet",
            mappings,
            MAPPING,
            kind="place_to_city",
        )
    )
    value["tables"] = tables
    write_manifest(manifest, value)
    query_points = np.asarray(points, dtype=np.float64)
    np.save(output / "clustered.npy", query_points, allow_pickle=False)
    np.random.default_rng(20261002).shuffle(query_points)
    np.save(output / "shuffled.npy", query_points, allow_pickle=False)
    return export(manifest, release, output / "pack", shard_bytes=4 * 1024 * 1024)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(create(parser.parse_args().output))

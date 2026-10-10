"""Reconstruct bounded pilot inputs without ever executing a real-workspace stage."""

import json
from pathlib import Path
from typing import Any

import duckdb

from pipeline.config import Config
from pipeline.engines.cells.windows import expanded
from pipeline.engines.hierarchy import descendants
from pipeline.engines.reconcile import build, catalog, inputs
from pipeline.engines.store.areas import insert_area
from pipeline.engines.store.database import connect
from pipeline.engines.store.schema import create_areas
from pipeline.migration.paths import legacy_relative
from pipeline.runtime.paths import located

Row = dict[str, Any]


def artifact(root: Path, name: str) -> Path:
    return located(root, legacy_relative(name, root))


def manifest(root: Path, name: str) -> Row:
    value: Row = json.loads(artifact(root, name).read_bytes())
    return value


def country(root: Path, output: Path, cc: str, policy: Row, config: Config) -> Path:
    paths = {}
    for source in config.engines.reconcile_sources:
        if source == "osm_land":
            continue
        value = manifest(root, f"normalized/{source}/manifest.json")
        for kind in config.engines.reconcile_sources[source]:
            paths[source + "_" + kind] = [
                str(artifact(root, row["path"]))
                for row in value["partitions"]
                if row["kind"] == kind
            ]
    limits = config.engines.limits
    extract = output / "extract"
    db = inputs.query_engine(paths, output, config.resources, limits)
    try:
        inputs.sovereigns(db, policy)
        inputs.extract(db, cc, extract, limits)
    finally:
        db.close()
    linked = catalog.catalog(extract, output / "links.sqlite", policy, limits)
    return build.build_country(
        linked, extract, output / f"{cc}.sqlite", cc, policy, limits
    )


def land(
    root: Path, output: Path, block: str, policy: Row, config: Config
) -> tuple[Path, int]:
    _, coordinates = descendants(int(block, 16), config.h3.cell_resolution)
    bounds = (
        float(coordinates[:, 1].min()),
        float(coordinates[:, 0].min()),
        float(coordinates[:, 1].max()),
        float(coordinates[:, 0].max()),
    )
    windows = expanded(bounds, policy["offshore_m"])
    parts = manifest(root, "normalized/osm_land/manifest.json")["partitions"]
    path = output / "land.sqlite"
    destination = connect(path, cache_kib=config.engines.limits.sqlite_cache_kib)
    count = 0
    try:
        create_areas(destination)
        with duckdb.connect() as db:
            db.execute("SET memory_limit=?", [config.resources.duckdb_memory])
            db.execute("SET threads=?", [config.resources.duckdb_threads])
            for part in parts:
                db.read_parquet(str(artifact(root, part["path"]))).create_view(
                    "land", replace=True
                )
                terms, parameters = [], []
                for west, east, south, north in windows:
                    terms.append("(xmax>=? AND xmin<=? AND ymax>=? AND ymin<=?)")
                    parameters.extend([west, east, south, north])
                reader = db.execute(
                    "SELECT * FROM land WHERE " + " OR ".join(terms), parameters
                ).to_arrow_reader(config.engines.limits.source_batch_rows)
                for batch in reader:
                    for row in batch.to_pylist():
                        insert_area(
                            destination,
                            row["source_id"],
                            "land",
                            0,
                            row["geometry"],
                            tuple(row[key] for key in ("xmin", "ymin", "xmax", "ymax")),
                            part["path"],
                        )
                        count += 1
                destination.commit()
    finally:
        destination.close()
    return path, count

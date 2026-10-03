"""Stream country envelopes and compute a complete block dependency index."""

import json
import sqlite3
from pathlib import Path

import duckdb
import shapely
from h3.api import basic_int as h3

from pipeline.config.engines import EngineLimits
from pipeline.config.schema import H3, Resources
from pipeline.engines.reconcile.common import Row, check_database, encode
from pipeline.engines.reconcile.matching import default_perspective
from pipeline.runtime.jsonio import atomic_output

from .blocks import describe
from .planning import Dependencies


def inventory(
    sources: dict[str, list[str]],
    policy: Row,
    resources: Resources,
    limits: EngineLimits,
) -> Row:
    records: list[tuple[str, float, float, float, float]] = []
    expected: set[str] = set()
    with duckdb.connect() as db:
        db.execute("SET memory_limit=?", [resources.duckdb_memory])
        db.execute("SET threads=?", [resources.duckdb_threads])
        for source, paths in sources.items():
            if not paths:
                continue
            db.read_parquet(paths).create_view("parts", replace=True)
            expected.update(
                str(row[0])
                for row in db.execute(
                    "SELECT DISTINCT country_code FROM parts "
                    "WHERE country_code IS NOT NULL"
                ).fetchall()
            )
            if source == "geonames":
                continue
            condition = (
                "subtype IN ('country','dependency')"
                if source == "overture"
                else "admin_level='ADM0'"
            )
            reader = db.execute(
                "SELECT country_code,geometry,provenance,license FROM parts "
                f"WHERE country_code IS NOT NULL AND {condition}"
            ).to_arrow_reader(limits.source_batch_rows)
            for batch in reader:
                for row in batch.to_pylist():
                    if source == "overture" and not default_perspective(row):
                        continue
                    if (
                        source == "geoboundaries"
                        and row["license"] not in policy["compatible_gb_licenses"]
                    ):
                        continue
                    shape = shapely.from_wkb(row["geometry"])
                    records.extend(
                        (row["country_code"], *part.bounds)
                        for part in shapely.get_parts(shape)
                    )
    return {"expected": sorted(expected), "bounds": records}


def index(
    path: Path, value: Row, policy: Row, resolution: H3, selected: list[str]
) -> None:
    dependencies = Dependencies(value, policy["offshore_m"])
    roots = (
        sorted(int(key, 16) for key in selected)
        if selected
        else sorted(
            child
            for parent in h3.get_res0_cells()
            for child in h3.cell_to_children(parent, resolution.block_resolution)
        )
    )
    with atomic_output(path) as temporary:
        db = sqlite3.connect(temporary)
        try:
            db.execute(
                "CREATE TABLE blocks(root TEXT PRIMARY KEY,bounds TEXT,countries TEXT)"
            )
            for root in roots:
                row = describe(root, dependencies, resolution.cell_resolution)
                db.execute(
                    "INSERT INTO blocks VALUES(?,?,?)",
                    (row["root"], encode(row["bounds"]), encode(row["countries"])),
                )
            db.commit()
            # Decode before publication, including ocean entries with no countries.
            for bounds, countries in db.execute("SELECT bounds,countries FROM blocks"):
                json.loads(bounds)
                json.loads(countries)
        finally:
            db.close()
        check_database(temporary)

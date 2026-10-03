"""Bounded country extraction from explicitly supplied source partitions."""

import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from pipeline.config.engines import EngineLimits
from pipeline.config.schema import Resources
from pipeline.runtime.jsonio import atomic_output

from .common import Row
from .matching import default_perspective


def query_engine(
    paths: dict[str, list[str]], work: Path, resources: Resources, limits: EngineLimits
) -> duckdb.DuckDBPyConnection:
    db = duckdb.connect()
    db.execute("SET memory_limit=?", [resources.duckdb_memory])
    db.execute("SET threads=?", [resources.duckdb_threads])
    db.execute("SET preserve_insertion_order=false")
    db.execute("SET temp_directory=?", [str(work / "spill")])
    db.execute("SET max_temp_directory_size=?", [f"{limits.duckdb_spill_bytes}B"])
    for name, files in paths.items():
        if files:
            db.read_parquet(files).create_view(name)
    return db


def extract(
    db: duckdb.DuckDBPyConnection, country: str, root: Path, limits: EngineLimits
) -> list[Path]:
    outputs = []
    for source in (
        "geonames_places",
        "overture_places",
        "overture_areas",
        "geoboundaries_areas",
        "geonames_names",
    ):
        where = "country_code = ?"
        if source.startswith("overture"):
            where += (
                " AND subtype IN ('country','dependency','region',"
                "'county','localadmin','locality')"
            )
        if source == "geonames_names":
            where = (
                "language='wkdt' AND entity_source_id IN "
                "(SELECT source_id FROM geonames_places WHERE country_code=?)"
            )
        path = root / f"{source}.parquet"
        with atomic_output(path) as temporary:
            db.sql(
                f"SELECT * FROM {source} WHERE {where}", params=[country]
            ).write_parquet(
                str(temporary),
                compression="zstd",
                row_group_size=limits.extract_row_group_rows,
            )
            pq.read_metadata(temporary)
        outputs.append(path)
    return outputs


def sovereigns(db: duckdb.DuckDBPyConnection, policy: Row) -> None:
    """Derive dependency parents from pinned source IDs, preserving conventions."""
    records = db.sql(
        "SELECT source_id,country_code,name,name_en,provenance "
        "FROM overture_places WHERE subtype IN ('country','dependency')"
    ).fetchall()
    countries = {r[0]: [r[1], r[3] or r[2]] for r in records}
    for identity, cc, _, _, evidence in records:
        if not default_perspective({"provenance": evidence}):
            continue
        hierarchies = json.loads(evidence)["upstream"].get("hierarchies") or []
        parents = {
            node["division_id"]
            for hierarchy in hierarchies
            for node in hierarchy
            if node["subtype"] == "country" and node["division_id"] != identity
        }
        if len(parents) == 1:
            parent = countries.get(next(iter(parents)))
            if parent and parent[0] != cc:
                policy["sovereigns"].setdefault(cc, parent)

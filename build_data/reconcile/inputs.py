"""Verify acquisition manifests, then checkpoint bounded country extracts."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from build_data.acquire import Ledger, Workspace, atomic_output, current_partitions
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint
from build_data.acquire.schemas import Kind

from .common import Row
from .matching import default_perspective

KINDS: dict[str, tuple[Kind, ...]] = {
    "overture": ("areas", "places"),
    "geonames": ("places", "names"),
    "geoboundaries": ("areas",),
    "osm_land": ("areas",),
}


def verified_inputs(workspace: Workspace) -> tuple[dict[str, list[str]], Row]:
    paths: dict[str, list[str]] = {}
    manifests: Row = {}
    for source, kinds in KINDS.items():
        for kind in kinds:
            print(f"verify {source}/{kind}", flush=True)
            paths[f"{source}_{kind}"] = [
                str(p) for p in current_partitions(workspace, source, kind)
            ]
        manifests[source] = read_json(workspace.normalized(source) / "manifest.json")
    return paths, manifests


def query_engine(paths: dict[str, list[str]], work: Path) -> duckdb.DuckDBPyConnection:
    db = duckdb.connect()
    db.execute("SET memory_limit='1GB'")
    db.execute("SET threads=1")
    db.execute("SET preserve_insertion_order=false")
    db.execute("SET temp_directory=?", [str(work / "spill")])
    for name, files in paths.items():
        db.read_parquet(files).create_view(name)
    return db


def extract(
    workspace: Workspace, db: duckdb.DuckDBPyConnection, country: str, inputs: str
) -> Path:
    digest = fingerprint({"source_inputs": inputs, "extract": 1, "country": country})
    root = workspace.work / "reconcile" / "extract" / digest / country
    ledger = Ledger(workspace.ledger_path)
    if ledger.is_complete("reconcile.extract", country, digest):
        return root
    root.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
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
                " AND subtype IN "
                "('country','dependency','region','county','localadmin','locality')"
            )
        if source == "geonames_names":
            where = (
                "language='wkdt' AND entity_source_id IN "
                "(SELECT source_id FROM geonames_places WHERE country_code=?)"
            )
        path = root / f"{source}.parquet"
        with atomic_output(path, _check_parquet) as temp:
            db.sql(
                f"SELECT * FROM {source} WHERE {where}", params=[country]
            ).write_parquet(str(temp), compression="zstd", row_group_size=2048)
        outputs.append(path)
    ledger.complete("reconcile.extract", country, digest, outputs)
    print(f"extract {country}: complete", flush=True)
    return root


def _check_parquet(path: Path) -> None:
    pq.read_metadata(path)


def sovereigns(db: duckdb.DuckDBPyConnection, policy: Row) -> None:
    """Derive other dependencies' sovereign parents from pinned source IDs."""
    records = db.sql(
        "SELECT source_id,country_code,name,name_en,provenance FROM overture_places "
        "WHERE subtype IN ('country','dependency')"
    ).fetchall()
    countries = {r[0]: [r[1], r[3] or r[2]] for r in records}
    for identity, cc, _, _, evidence in records:
        if not default_perspective({"provenance": evidence}):
            continue
        hierarchies = json.loads(evidence)["upstream"].get("hierarchies") or []
        parents = {
            node["division_id"]
            for h in hierarchies
            for node in h
            if node["subtype"] == "country" and node["division_id"] != identity
        }
        if len(parents) == 1:
            parent = countries.get(next(iter(parents)))
            if parent and parent[0] != cc:
                policy["sovereigns"].setdefault(cc, parent)

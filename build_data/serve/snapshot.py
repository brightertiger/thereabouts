"""Verify a manifest-listed golden snapshot without touching its workspace ledger."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from h3.api import basic_int as h3

from build_data.cities.schemas import CITIES, MAPPING
from build_data.golden.schemas import CELLS, PLACES
from thereabouts.packs.jsonio import check_file, parse, relative_file, sha256, string

Row = dict[str, Any]
BATCH_ROWS = 1024
PLACE_SCHEMA = pa.schema(
    [
        *PLACES,
        *[
            pa.field(n, pa.string())
            for n in ("normalized_city_id", "normalization_method", "settlement_kind")
        ],
    ]
)
SCHEMAS = {
    "cells": CELLS,
    "places": PLACE_SCHEMA,
    "canonical_cities": CITIES,
    "place_to_city": MAPPING,
}
SPATIAL_KINDS = {"postal_codes", "airports", "trade_locations", "ip_ranges"}
INTEGRITY = {
    "duplicate_place_ids",
    "missing_cell_place_ids",
    "missing_parent_rows",
    "missing_sovereign_rows",
}
NORMALIZATION_INTEGRITY = {
    "unmapped_places",
    "dangling_mapping",
    "dangling_canonical",
    "cross_country_mapping",
}


@dataclass(frozen=True)
class Snapshot:
    path: Path
    root: Path
    digest: str
    manifest: Row

    def tables(self, kind: str) -> list[Row]:
        return sorted(
            (r for r in self.manifest["tables"] if r["kind"] == kind),
            key=lambda r: r["path"],
        )

    def file(self, record: Row) -> Path:
        return relative_file(self.root, record["path"])

    def recheck(self) -> None:
        if sha256(self.path) != self.digest:
            raise ValueError("Golden manifest changed during export")
        for r in [*self.manifest["tables"], *self.manifest["verification_artifacts"]]:
            check_file(self.root, r, full=True)


def read_snapshot(path: Path) -> Snapshot:
    path = path.resolve()
    value = parse(path.read_bytes())
    if value.get("schema_version") != "golden-2" or value.get("completed") is not True:
        raise ValueError("A completed, verified golden-2 manifest is required")
    if (value.get("reference_resolution"), value.get("block_resolution")) != (8, 3):
        raise ValueError("Expected golden resolution 8 with resolution-3 blocks")
    root_name = string(value["data_root"])
    if Path(root_name).is_absolute():
        raise ValueError("Golden data_root must be relative to the manifest")
    root = (path.parent / root_name).resolve()
    snapshot = Snapshot(path, root, sha256(path), value)
    snapshot.recheck()
    paths: set[str] = set()
    blocks: set[str] = set()
    for record in value["tables"]:
        if record["path"] in paths:
            raise ValueError("Repeated golden table")
        paths.add(record["path"])
        kind = record["kind"]
        parquet = pq.ParquetFile(snapshot.file(record))
        if parquet.metadata.num_rows != record["rows"]:
            raise ValueError("Golden table row count mismatch")
        if kind in SCHEMAS:
            expected = SCHEMAS[kind]
            actual = parquet.schema_arrow
            if set(actual.names) != set(expected.names) or any(
                actual.field(f.name) != f for f in expected
            ):
                raise ValueError(f"Golden {kind} schema mismatch")
        if kind == "cells":
            block = string(record["block"])
            if (
                block in blocks
                or not h3.is_valid_cell(int(block, 16))
                or h3.get_resolution(int(block, 16)) != 3
                or h3.int_to_str(int(block, 16)) != block
            ):
                raise ValueError("Invalid or repeated golden block")
            blocks.add(block)
        statuses = [
            name
            for name in ("cell_status", "link_status")
            if name in parquet.schema_arrow.names
        ]
        if kind in SPATIAL_KINDS and "cell_status" not in statuses:
            raise ValueError("Missing spatial join status")
        if statuses:
            for batch in parquet.iter_batches(batch_size=BATCH_ROWS, columns=statuses):
                if any("pending" in column.to_pylist() for column in batch.columns):
                    raise ValueError("Pending golden lookup joins")
    if any(not snapshot.tables(kind) for kind in SCHEMAS):
        raise ValueError("Golden snapshot lacks required normalized tables")
    artifacts = value["verification_artifacts"]
    artifact_paths = [r["path"] for r in artifacts]
    if len(set(artifact_paths)) != len(artifact_paths) or paths.intersection(
        artifact_paths
    ):
        raise ValueError("Repeated verification artifact")
    quality = [r for r in artifacts if Path(r["path"]).name == "quality.json"]
    if len(quality) != 1:
        raise ValueError("Expected one verified golden quality report")
    report = parse(snapshot.file(quality[0]).read_bytes())
    for field, keys in (
        ("integrity", INTEGRITY),
        ("normalization_integrity", NORMALIZATION_INTEGRITY),
    ):
        if any(
            type(report[field].get(k)) is not int or report[field][k] != 0 for k in keys
        ):
            raise ValueError("Golden integrity verification has not passed")
    gates = report["failed_spatial_gates"]
    if set(gates) != {"footprints", "neighbours", "named", "all_boundaries"} or any(
        gates.values()
    ):
        raise ValueError("Golden spatial quality gates have not passed")
    if value["normalization"].get("completed") is not True:
        raise ValueError("Incomplete golden normalization generation")
    string(value["builder"])
    string(value["implementation"])
    return snapshot

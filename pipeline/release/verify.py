"""Verify release inventories without allowing paths to escape their directory."""

from pathlib import Path

import pyarrow.parquet as pq

from pipeline.config.schema import H3
from pipeline.engines.artifacts import read_json
from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.paths import located

from .cell_groups import verify_index
from .source import Row


def verify_dataset(root: Path) -> Row:
    manifest = read_json(root / "manifest.json")
    if (
        not manifest.get("completed")
        or not manifest.get("files")
        or not manifest.get("tables")
    ):
        raise ValueError("Incomplete release manifest")
    seen = set()
    seen_blocks: set[str] = set()
    grid = H3(
        cell_resolution=manifest["reference_resolution"],
        block_resolution=manifest["block_resolution"],
    )
    for record in manifest["files"]:
        path = located(root, record["path"])
        if record["path"] in seen:
            raise ValueError(f"Duplicate release file: {record['path']}")
        seen.add(record["path"])
        if (
            path.stat().st_size != record["size"]
            or sha256_file(path) != record["sha256"]
        ):
            raise ValueError(f"Release checksum mismatch: {record['path']}")
        if "rows" in record and pq.read_metadata(path).num_rows != record["rows"]:
            raise ValueError(f"Release row count mismatch: {record['path']}")
        if record.get("kind") == "cells":
            with pq.ParquetFile(path) as file:
                verify_index(record, file, grid, seen_blocks)
    for table in manifest["tables"]:
        if table not in manifest["files"]:
            raise ValueError("Release table is not in the verified file inventory")
    return manifest

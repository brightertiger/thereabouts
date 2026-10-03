"""Opt-in proof: Malaysian base cells, city products and both pilot variants."""

import os
import shutil
import time
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from pipeline.config import load, policies
from pipeline.engines.cells.schemas import CELLS
from pipeline.engines.cities.engine import Engine
from pipeline.engines.cities.urban import Urban
from pipeline.engines.normalize_cells.blocks import transform
from pipeline.engines.storage import parquet
from pipeline.runtime.jsonio import sha256_file, write_json
from pipeline.runtime.resources import workspace_bytes

from .helpers import peak_rss
from .pilot_inputs import artifact, country, land, manifest
from .pilot_outputs import base_cells, city_products

# This deliberately selects the already measured input sample, not a world build.
BLOCK = "836505fffffffff"
COUNTRY = "MY"
RESERVATION = (
    350_000_000  # measured reconstruction 140,388,737 bytes + temporary writes
)


@pytest.mark.world
def test_retained_pilot_bytes(tmp_path: Path) -> None:
    value = os.environ.get("THEREABOUTS_PIPELINE_DATA")
    if not value:
        pytest.skip("set THEREABOUTS_PIPELINE_DATA for read-only pilot input")
    repository = Path(__file__).parents[2]
    assert tmp_path.is_relative_to(repository), "Use --basetemp inside the worktree"
    assert shutil.disk_usage(repository).free - RESERVATION > 5_000_000_000
    assert workspace_bytes(repository) + RESERVATION < 3_000_000_000
    root = Path(value)
    ledger = root / "work/ledger.sqlite3"
    before = sha256_file(ledger)
    started = time.monotonic()
    config = load(
        overrides=[
            "resources.duckdb_memory=512MB",
            "engines.limits.duckdb_spill_bytes=128000000",
        ]
    )
    policy = policies.reconcile()
    source = country(root, tmp_path, COUNTRY, policy, config)
    physical, feature_count = land(root, tmp_path, BLOCK, policy, config)
    base_pointer = manifest(root, "base_cells/current.json")
    base = manifest(root, base_pointer["manifest"]["path"])
    record = next(
        row
        for row in base["tables"]
        if row["kind"] == "cells" and row["block"] == BLOCK
    )
    base_result = base_cells(tmp_path, BLOCK, source, physical, policy, record, config)
    record = {**record, "path": str(tmp_path / base_result["path"])}
    city = manifest(root, "city_normalized/manifest.json")["countries"][COUNTRY]
    urban = Urban(
        [
            {**part, "path": str(artifact(root, part["path"]))}
            for part in manifest(root, "normalized/ghsl/manifest.json")["partitions"]
        ]
    )
    city_policy = policies.cities()
    city_index, city_results = city_products(
        tmp_path, source, urban, city_policy, city, config
    )
    selector = Engine(
        city_index,
        source,
        urban,
        city_policy,
        (physical, policy["offshore_m"]),
        config.engines.limits,
    )
    pilot = manifest(root, "work/v2-pilot-blocks/report.json")
    results = []
    for variant, radius in [("off", False), ("on", True)]:
        rows, counts = transform(record, {COUNTRY: selector}, radius)
        output = tmp_path / f"{variant}.parquet"
        made = parquet(
            tmp_path, output, rows, CELLS, config.engines.limits.parquet_batch_rows
        )
        expected = next(
            row for row in pilot[variant]["tables"] if row["block"] == BLOCK
        )
        assert pq.read_table(output).equals(
            pq.read_table(artifact(root, expected["path"]))
        )
        assert made["sha256"] == expected["sha256"]
        results.append({"block": BLOCK, "variant": variant, **made, "counts": counts})
    assert sha256_file(ledger) == before
    write_json(
        tmp_path / "measurements.json",
        {
            "seconds": time.monotonic() - started,
            "peak_rss_bytes": peak_rss(),
            "output_bytes": workspace_bytes(tmp_path),
            "land_features": feature_count,
            "results": [base_result, *city_results, *results],
            "real_ledger_sha256": before,
        },
    )

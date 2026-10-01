"""Osm land report."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import Workspace
from .artifacts import publish_report
from .lifecycle import finish_source
from .osm_land import RELEASE, SOURCE
from .osm_land_settings import SPOT_CHECKS, configuration
from .runtime import peak_rss_bytes


def _publish_manifest(
    workspace: Workspace,
    units: list[dict[str, str]],
    counts: dict[str, int],
    source_count: int,
    hits: dict[str, list[str]],
    auxiliary: list[Path],
    started: float,
    index: Path,
    notice: dict[str, object],
) -> None:
    if counts["rows"] != source_count:
        raise ValueError(
            f"Output count {counts['rows']} differs from source {source_count}"
        )
    checks = {
        name: {
            "longitude": x,
            "latitude": y,
            "expected_land": expected,
            "actual_land": bool(hits[name]),
            "source_ids": hits[name],
            "passed": bool(hits[name]) == expected,
        }
        for name, (x, y, expected) in SPOT_CHECKS.items()
    }
    latest_report = workspace.normalized(SOURCE) / "verification.json"
    previous = json.loads(latest_report.read_text()) if latest_report.exists() else {}
    if previous.get("input_index", str(index)) != str(index):
        previous = {}
    elapsed = time.monotonic() - started
    report_data: dict[str, object] = {
        **counts,
        "source_dbf_records": source_count,
        "source_shx_records": source_count,
        "input_index": str(index),
        "publisher_notice": notice,
        "publisher_count_basis": "ZIP README, SHX index entries and DBF header",
        "spot_checks": checks,
        "peak_rss_bytes": peak_rss_bytes(),
        "elapsed_seconds": elapsed,
        "first_run_elapsed_seconds": previous.get(
            "first_run_elapsed_seconds", previous.get("elapsed_seconds", elapsed)
        ),
        "peak_rss_all_runs_bytes": max(
            previous.get("peak_rss_all_runs_bytes", previous.get("peak_rss_bytes", 0)),
            peak_rss_bytes(),
        ),
        "kind_counts": {"land": counts["rows"]},
        "subtype_counts": {"split_land_polygon": counts["rows"]},
        "partition_count": len(units),
        "dropped_records": 0,
        "coastline_edges_classified": False,
        "spatial_partitioning": (
            "10-degree lower-left source-bbox buckets; "
            "intact source tiles may extend beyond bucket"
        ),
    }
    report = publish_report(workspace, SOURCE, report_data)
    if not all(item["passed"] for item in checks.values()):
        raise ValueError(f"OSM land spot checks failed; see {report}")
    finish_source(
        workspace, SOURCE, RELEASE, units, [*auxiliary, report, index], configuration()
    )

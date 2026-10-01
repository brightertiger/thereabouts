"""Overture report."""

from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from . import Ledger, Workspace
from .artifacts import publish_report
from .lifecycle import finish_source
from .overture import PUBLISHED_COUNTS, RELEASE_NOTES_URL, SOURCE
from .overture_settings import SPOTS, configuration
from .runtime import peak_rss_bytes


def _finish(
    workspace: Workspace,
    inventory: dict[str, Any],
    units: list[dict[str, str]],
    audits: list[Path],
    ledger: Ledger,
    db: sqlite3.Connection,
    started: float,
) -> None:
    totals: Counter[str] = Counter()
    rows: Counter[str] = Counter()
    subtypes: dict[str, Counter[str]] = {"areas": Counter(), "places": Counter()}
    spots: dict[str, list[dict[str, Any]]] = {label: [] for label in SPOTS}
    size = 0
    completed_unit_seconds = 0.0
    peak_rss = peak_rss_bytes()
    for unit, path in zip(units, audits, strict=True):
        outputs = ledger.completed_outputs(
            unit["stage"], unit["unit_id"], unit["inputs_hash"]
        )
        if outputs is None:
            raise ValueError("Completed normalization output failed final verification")
        size += sum(output.stat().st_size for output in outputs)
        audit = json.loads(path.read_text())
        completed_unit_seconds += audit["elapsed_seconds"]
        peak_rss = max(peak_rss, audit["peak_rss_bytes"])
        totals.update(audit["counts"])
        rows.update(audit["output_rows"])
        subtypes[audit["kind"]].update(audit["subtypes"])
        for label, matches in audit["spot_checks"].items():
            spots[label].extend(matches)
    missing_parents = db.execute(
        "SELECT COUNT(*) FROM entities e LEFT JOIN entities p ON e.parent=p.id "
        "WHERE e.parent IS NOT NULL AND p.id IS NULL"
    ).fetchone()[0]
    summary: dict[str, Any] = {
        "source_release": inventory["source_release"],
        "counts": dict(totals),
        "rows": dict(rows),
        "input_subtypes": {kind: dict(counts) for kind, counts in subtypes.items()},
        "spot_checks": spots,
        "missing_parent_ids": missing_parents,
        "output_bytes": size,
        "elapsed_seconds": time.monotonic() - started,
        "completed_unit_seconds": completed_unit_seconds,
        "peak_rss_bytes": peak_rss,
        "completed_at": datetime.now().astimezone().isoformat(),
    }
    expected: Counter[str] = Counter()
    for obj in inventory["objects"]:
        with pq.ParquetFile(workspace.raw(SOURCE) / obj["relative_path"]) as parquet:
            expected["places" if obj["type"] == "division" else "areas"] += (
                parquet.metadata.num_rows
            )
    actual = {kind: sum(counts.values()) for kind, counts in subtypes.items()}
    if actual != dict(expected):
        raise ValueError("Final source footer count mismatch")
    summary["source_footer_counts"] = dict(expected)
    published = PUBLISHED_COUNTS.get(inventory["source_release"])
    if published is not None and expected != {
        "places": published["division"],
        "areas": published["division_area"],
    }:
        raise ValueError("Source footer counts disagree with published release counts")
    summary["publisher_counts"] = published
    summary["publisher_counts_url"] = RELEASE_NOTES_URL if published else None
    summary["spot_check_roles"] = {
        label: {
            role: sorted(
                {
                    match["name_en"] or match["name"]
                    for match in matches
                    if match["subtype"] in types
                }
            )
            for role, types in {
                "country_or_territory": ("country", "dependency"),
                "state_like": ("region", "macroregion"),
                "locality": ("locality",),
            }.items()
        }
        for label, matches in spots.items()
    }
    db.close()
    path = publish_report(workspace, SOURCE, summary)
    finish_source(
        workspace,
        SOURCE,
        inventory["source_release"],
        units,
        [*audits, path],
        configuration(),
        inputs=[
            workspace.raw(SOURCE) / obj["relative_path"] for obj in inventory["objects"]
        ],
    )
    print(
        f"NORMALIZATION COMPLETE: {dict(rows)}, "
        f"{totals['rejected_features']} rejects, {size} bytes, "
        f"{time.monotonic() - started:.1f}s",
        flush=True,
    )

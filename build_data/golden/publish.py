"""Publish the current partial snapshot, resource counts and attribution draft."""

from __future__ import annotations

import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from build_data.acquire import Ledger, Workspace
from build_data.acquire.io import fingerprint, write_json
from build_data.reconcile.common import Row

from .cells import builder
from .inputs import Inputs

LICENSES = Path(__file__).with_name("licenses.md").read_text(encoding="utf-8")


def publish(
    workspace: Workspace,
    inputs: Inputs,
    tables: list[Row],
    progress: Row,
    checks: Row | None = None,
) -> Row:
    root = workspace.root / "golden"
    root.mkdir(parents=True, exist_ok=True)
    rows: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    disagreements: dict[str, Counter[str]] = {}
    for table in tables:
        rows[table["kind"]] += table["rows"]
        sizes[table["kind"]] += table["size"]
        if "counts" in table:
            disagreements.setdefault(table["kind"], Counter()).update(table["counts"])
    quality = {
        "rows": dict(rows),
        "bytes": dict(sizes),
        "lookup_counts": {k: dict(v) for k, v in disagreements.items()},
        "progress": progress,
        "free_bytes": shutil.disk_usage(workspace.root).free,
        "checks": checks or {"status": "not yet evaluated"},
    }
    write_json(root / "quality.json", quality)
    (root / "DATA_LICENSES.md").write_text(LICENSES, encoding="utf-8")
    (root / "DATASET_CARD.md").write_text(
        "# Golden dataset card — draft\n\n"
        "Canonical reconciled places and a compact H3 resolution-8 reference table.\n"
        "Use the original r8 key and walk to a stored ancestor; converting a point\n"
        "directly at a coarse resolution changes the reference centre.\n\n"
        f"Snapshot countries: {len(inputs.countries)}. "
        f"Completion: {progress.get('completed', False)}.\n"
        "Coverage is physical OSM land plus the policy's 1 km offshore band. Offshore\n"
        "labels use the projected land point; fallback cities use the original\n"
        "centre, within the chosen country and inclusive 50 km cutoff.\n\n"
        "Rows from unfinished blocks retain pending status. Ineligible ocean,\n"
        "unlocated source rows and unresolved eligible land are distinct. Source\n"
        "country codes remain beside spatial country codes; disagreements are\n"
        "counted without adjudication. IP coordinates describe database estimates.\n\n"
        "Population-ranked municipalities may contain distinct settlements;\n"
        "unlinked localities may be misclassified. Results inherit source dates,\n"
        "disputed-boundary perspectives and the reconciliation's city conventions.\n"
        "Source agreement checks are not independent holdout accuracy. Cell-centre\n"
        "quantization can change the original named-point result.\n\n"
        "See quality.json for counts, pending work and evaluated checks,\n"
        "DATA_LICENSES.md for attribution, and docs/GOLDEN_DATASET.md for columns.\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "golden-1",
        "reference_resolution": 8,
        "block_resolution": 3,
        "created_at": datetime.now(UTC).isoformat(),
        "completed": progress.get("completed", False),
        "inputs": {
            "identity": inputs.identity,
            "countries": inputs.countries,
            "land": inputs.land,
            "reconciliation_builder": inputs.builder,
            "golden_builder": builder(),
        },
        "policy": inputs.policy,
        "tables": tables,
        "quality": "quality.json",
        "license_summary": "DATA_LICENSES.md",
        "dataset_card": "DATASET_CARD.md",
    }
    write_json(root / "manifest.json", manifest)
    Ledger(workspace.ledger_path).complete(
        "golden.manifest",
        "current",
        fingerprint(manifest),
        [
            root / "manifest.json",
            root / "quality.json",
            root / "DATA_LICENSES.md",
            root / "DATASET_CARD.md",
        ],
    )
    return quality

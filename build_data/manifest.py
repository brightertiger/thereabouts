"""Deterministic provenance, transformation audit and data attribution."""

import json
from importlib.metadata import version
from pathlib import Path

import numpy as np
import shapely

from pyofflinegeocoder.schema import POLICY_ID, SCHEMA_VERSION

from .normalize import Audit, BBox
from .sources import provenance, sha256


def write_manifest(
    path: Path,
    bounds: BBox | None,
    audit: Audit,
    snapshot_id: str,
    counts: dict[str, int],
) -> None:
    files = {
        p.name: {"size": p.stat().st_size, "sha256": sha256(p)}
        for p in sorted(path.glob("*.npy"))
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "policy_id": POLICY_ID,
        "sources": provenance(),
        "files": files,
        "coverage_bbox": bounds,
        "coverage_description": "Global Natural Earth terrestrial coverage"
        if bounds is None
        else (
            f"Regional bounding box {bounds}; "
            "globally complete nearest candidates within coverage"
        ),
        "attribution": [
            "Made with Natural Earth.",
            "GeoNames (geonames.org), CC BY 4.0.",
        ],
        "transformations": (
            "Repaired polygon parts; no simplification; placeholders removed; "
            "admin coverage fills inland-water holes; regional clipping "
            "and certified nearest candidate subset."
        ),
        "counts": {
            "countries": counts["countries"],
            "admin1": counts["admin1"],
            "places": counts["places"],
        },
        "normalization_log": audit,
        "builder_versions": {
            "numpy": np.__version__,
            "shapely": shapely.__version__,
            "geos": shapely.geos_version_string,
            "scipy": version("scipy"),
            "pyshp": version("pyshp"),
        },
    }
    (path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (path / "DATA_LICENSES.txt").write_text(
        "Natural Earth 5.1.1: public domain. https://www.naturalearthdata.com/about/terms-of-use/\n"
        "Made with Natural Earth.\nGeoNames, 2026-10-01: CC BY 4.0. https://www.geonames.org/\n"
        "https://creativecommons.org/licenses/by/4.0/\n"
        "Derived data: selected fields, geometry repair/clipping, "
        "optional regional settlement selection.\n"
        "Source data is provided without warranty. No endorsement by source authors.\n",
        encoding="utf-8",
    )

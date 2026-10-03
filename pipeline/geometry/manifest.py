"""Explicit local data discovery and small manifest validation."""

import json
from pathlib import Path
from typing import Any

from thereabouts.format import CITY_CUTOFF_KM

from .errors import DamagedPackError, UnsupportedSchemaError

SCHEMA = "h3-table-v1"


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        if (path / "manifest.json").stat().st_size > 2_000_000:
            raise ValueError("manifest too large")
        value = json.loads((path / "manifest.json").read_text())
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        if value.get("schema_version") != SCHEMA:
            raise UnsupportedSchemaError("Expected an H3 table pack")
        if value.get("resolution") not in (6, 7, 8):
            raise ValueError("unsupported finest resolution")
        if value.get("layout") != "combined":
            raise ValueError("unsupported table layout")
        if value.get("city_cutoff_km") != CITY_CUTOFF_KM:
            raise ValueError("unsupported city cutoff")
        if not isinstance(value.get("files"), dict):
            raise ValueError("missing file directory")
        return value
    except (OSError, ValueError, TypeError) as exc:
        raise DamagedPackError(f"Invalid table manifest: {exc}") from exc

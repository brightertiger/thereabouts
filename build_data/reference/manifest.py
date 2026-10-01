"""Small manifest validation and explicit local data discovery."""

import json
from pathlib import Path
from typing import Any

from pyofflinegeocoder.errors import (
    DamagedPackError,
    UnsupportedSchemaError,
)

from .schema import ARRAY_DTYPES, POLICY_ID, SCHEMA_VERSION


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        if (path / "manifest.json").stat().st_size > 2_000_000:
            raise ValueError("manifest is too large")
        value = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(
            value.get("schema_version"), str
        ):
            raise ValueError("missing schema version")
        if value["schema_version"] != SCHEMA_VERSION:
            raise UnsupportedSchemaError(
                f"Unsupported pack schema: {value['schema_version']!r}"
            )
        validate_manifest(value)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DamagedPackError(f"Invalid pack manifest at {path}: {exc}") from exc
    return value


def validate_manifest(value: dict[str, Any]) -> None:
    for key in ("snapshot_id", "policy_id", "coverage_description"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise ValueError(f"invalid {key}")
    if value["policy_id"] != POLICY_ID:
        raise ValueError("unsupported policy")
    if not isinstance(value.get("attribution"), list) or not all(
        isinstance(item, str) for item in value["attribution"]
    ):
        raise ValueError("invalid attribution")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("missing sources")
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("invalid source record")
        for key in ("name", "date", "url", "sha256", "license", "attribution"):
            if not isinstance(source.get(key), str):
                raise ValueError(f"invalid source {key}")
    bounds = value["coverage_bbox"]
    if bounds is not None:
        if not isinstance(bounds, list) or len(bounds) != 4:
            raise ValueError("invalid coverage bounding box")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in bounds):
            raise ValueError("invalid coverage coordinates")
        w, s, e, n = bounds
        if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
            raise ValueError("invalid coverage bounding box")
    files = value.get("files")
    if not isinstance(files, dict) or set(files) != {f"{n}.npy" for n in ARRAY_DTYPES}:
        raise ValueError("unexpected array file directory")
    for entry in files.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("size"), int):
            raise ValueError("invalid file size")
        digest = entry.get("sha256", "")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("invalid checksum")
        int(digest, 16)

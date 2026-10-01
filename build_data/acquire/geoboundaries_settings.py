"""Geoboundaries settings."""

from __future__ import annotations

from . import SCHEMA_HASHES

BUILDER_VERSION = "2"

POLICY_VERSION = "retain-all-admin-layers-1"

MAX_GEOMETRY_BYTES = 6_000_000

MAX_SHAPE_BYTES = 120_000_000

BATCH_BYTES = 16_000_000

PARTITION_BYTES = 60_000_000

MAX_ROWS = 2048

KINDS = {"ADM0": "country", "ADM1": "state", "ADM2": "county"}


def configuration() -> dict[str, object]:
    return {
        "builder": BUILDER_VERSION,
        "policy": POLICY_VERSION,
        "schemas": SCHEMA_HASHES,
        "max_geometry_bytes": MAX_GEOMETRY_BYTES,
        "max_shape_bytes": MAX_SHAPE_BYTES,
    }

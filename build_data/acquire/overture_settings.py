"""Overture settings."""

from __future__ import annotations

import pyarrow as pa
import shapely

from .schemas import CORE_SCHEMA_HASHES

BUILDER = "overture-normalize-1"

POLICY = "retain-all-subtypes-no-perspective-selection-1"

GEOMETRY_BYTES = 5_000_000

BATCH_BYTES = 12_000_000

PART_BYTES = 48_000_000

SPOTS = {
    "lower Manhattan": (-74.0060, 40.7128),
    "central Tokyo": (139.6917, 35.6895),
    "Singapore": (103.8198, 1.3521),
    "Pristina": (21.1655, 42.6629),
    "Cayenne": (-52.3333, 4.9333),
}


def configuration() -> dict[str, object]:
    return {
        "builder": BUILDER,
        "policy": POLICY,
        "schemas": CORE_SCHEMA_HASHES,
        "geometry_bytes": GEOMETRY_BYTES,
        "batch_bytes": BATCH_BYTES,
        "part_bytes": PART_BYTES,
        "shapely": shapely.__version__,
        "geos": shapely.geos_version_string,
        "pyarrow": pa.__version__,
    }

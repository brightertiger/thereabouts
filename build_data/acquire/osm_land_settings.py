"""Osm land settings."""

from __future__ import annotations

import shapefile
import shapely

from . import SCHEMA_HASHES
from .osm_land import BUILDER_VERSION, POLICY_VERSION, RELEASE, SOURCE_URL

GRID_DEGREES = 10

MAX_UNIT_RECORDS = 1000

MAX_UNIT_BYTES = 8_000_000

MAX_SOURCE_RECORD_BYTES = 6_000_000

RSS_LIMIT_BYTES = 3_000_000_000

SPOT_CHECKS = {
    "Lagos": (3.3947, 6.4541, True),
    "Hong Kong Central": (114.1582, 22.2819, True),
    "Monaco": (7.4246, 43.7384, True),
    "Mombasa": (39.6682, -4.0435, True),
    "mid-Atlantic": (-30.0, 0.0, False),
    "Antarctic interior": (0.0, -89.0, True),
    "dateline east land": (179.5, 68.0, True),
    "dateline west land": (-179.5, 68.0, True),
}


def configuration() -> dict[str, object]:
    return {
        "builder": BUILDER_VERSION,
        "policy": POLICY_VERSION,
        "schemas": SCHEMA_HASHES,
        "grid_degrees": GRID_DEGREES,
        "max_records": MAX_UNIT_RECORDS,
        "max_unit_bytes": MAX_UNIT_BYTES,
        "max_source_record_bytes": MAX_SOURCE_RECORD_BYTES,
        "shapely": shapely.__version__,
        "pyshp": shapefile.__version__,
        "release": RELEASE,
        "source_url": SOURCE_URL,
    }

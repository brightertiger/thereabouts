"""Geonames settings."""

from __future__ import annotations

from . import SCHEMA_HASHES
from .geonames_rows import BUILDER_VERSION, POLICY_VERSION
from .geonames_tsv import CHUNK_BYTES, MAX_LINE_BYTES

BATCH_ROWS = 4096

PARTITION_BYTES = 48_000_000

BATCH_BYTES = 12_000_000

READ_BYTES = 1024 * 1024

STAGE = "geonames.normalize"

SPOTS = {
    "2332459": ("Lagos", "NG", 1_000_000, 40_000_000),
    "1819729": ("Hong Kong", "HK", 1_000_000, 15_000_000),
    "1850147": ("Tokyo", "JP", 1_000_000, 50_000_000),
    "5128581": ("New York City", "US", 1_000_000, 30_000_000),
    "1880252": ("Singapore", "SG", 1_000_000, 10_000_000),
    "2993458": ("Monaco", "MC", 500, 100_000),
}


def configuration() -> dict[str, object]:
    return {
        "builder": BUILDER_VERSION,
        "policy": POLICY_VERSION,
        "schemas": SCHEMA_HASHES,
        "chunk_bytes": CHUNK_BYTES,
        "max_line_bytes": MAX_LINE_BYTES,
        "batch_rows": BATCH_ROWS,
        "partition_bytes": PARTITION_BYTES,
    }

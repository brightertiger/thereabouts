"""Lossless, reproducible storage for independent forward-source oracles."""

import gzip
import json
from pathlib import Path
from typing import Any, cast


def read_source(path: Path) -> dict[str, Any]:
    """Read a committed gzip JSON extract without requiring the real dataset."""
    value = json.loads(gzip.decompress(path.read_bytes()))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a source object: {path}")
    return cast(dict[str, Any], value)


def write_source(path: Path, value: dict[str, Any]) -> None:
    """Omit gzip timestamps so rebuilding identical observations is byte stable."""
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.write_bytes(gzip.compress(payload.encode(), mtime=0))

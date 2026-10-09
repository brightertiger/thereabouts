"""Publisher attestations that pinned bytes must satisfy besides their SHA256."""

import gzip
import hashlib
from pathlib import Path
from typing import Any, BinaryIO, cast

COVERAGE = {"file", "decompressed"}


def verify_publisher(
    path: Path, metadata: dict[str, Any], chunk_bytes: int, label: str
) -> None:
    """Check a recorded publisher MD5; DB-IP publishes it for the gunzipped CSV."""
    expected = metadata.get("publisher_md5")
    if expected is None:
        return
    covers = metadata.get("publisher_md5_covers", "file")
    if covers not in COVERAGE:
        raise ValueError(f"Unknown publisher_md5_covers: {covers}")
    digest = hashlib.md5()
    with path.open("rb") as raw:
        stream = cast(BinaryIO, gzip.GzipFile(fileobj=raw)) if covers != "file" else raw
        while block := stream.read(chunk_bytes):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError(f"Publisher MD5 differs from the pinned bytes: {label}")

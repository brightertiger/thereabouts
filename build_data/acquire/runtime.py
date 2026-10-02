"""Process ownership, disk admission and resource measurements for all sources."""

import fcntl
import resource
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .lookup_catalog import LOOKUP_SOURCES
from .workspace import Workspace

SOURCE_LIMITS = {
    "ghsl": 100_000_000,
    **dict.fromkeys(LOOKUP_SOURCES, 6_000_000_000),
    "osm_land": 8_000_000_000,
    "overture": 25_000_000_000,
    "geonames": 10_000_000_000,
    "geoboundaries": 12_000_000_000,
}


@contextmanager
def single_run(workspace: Workspace, name: str) -> Iterator[None]:
    """Own a source (both stages) or the shared geometry worker, without waiting."""
    workspace.work.mkdir(parents=True, exist_ok=True)
    with (workspace.work / f"{name}.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                f"Another {name} process owns the source lock"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def disk_bytes(paths: Iterator[Path]) -> int:
    total = 0
    for path in paths:
        try:
            if path.is_file():
                total += path.stat().st_size
        except FileNotFoundError:
            continue  # Another source can publish or clean while we measure.
    return total


def source_budget(workspace: Workspace, source: str, required: int = 0) -> None:
    workspace.check_budget(required)
    if source in LOOKUP_SOURCES:
        roots_all = [
            root
            for name in LOOKUP_SOURCES
            for root in (
                workspace.raw(name),
                workspace.normalized(name),
                workspace.work / name,
            )
        ]
        total = sum(disk_bytes(root.rglob("*")) for root in roots_all)
        if total + required > 6_000_000_000:
            raise OSError("Additional lookups would exceed their shared 6 GB budget")
    roots = (
        workspace.raw(source),
        workspace.normalized(source),
        *workspace.work.glob(f"{source}*"),
    )
    used = sum(
        disk_bytes(iter((root,)) if root.is_file() else root.rglob("*"))
        for root in roots
    )
    if used + required > SOURCE_LIMITS[source]:
        raise OSError(
            f"{source} would exceed its {SOURCE_LIMITS[source] // 10**9} GB budget"
        )


def peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def resources(started: float) -> dict[str, object]:
    return {
        "elapsed_seconds": time.monotonic() - started,
        "peak_rss_bytes": peak_rss_bytes(),
    }

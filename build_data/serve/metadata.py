"""Export identities and canonical serving manifest publication."""

import platform
import sqlite3
import zlib
from pathlib import Path

import h3
import pyarrow

from build_data.acquire.io import atomic_output
from thereabouts.packs.jsonio import canonical, digest, integer, parse, sha256

from .snapshot import Row, Snapshot


def implementation() -> Row:
    root = Path(__file__).resolve().parents[2]
    files = [
        *Path(__file__).parent.glob("*.py"),
        *(root / "build_data/serve_codes").glob("*.py"),
        root / "build_data/golden/reader.py",
        root / "build_data/acquire/lookup_schemas.py",
        *(root / "src/thereabouts/packs").glob("*.py"),
        root / "build_data/acquire/io.py",
        root / "build_data/golden/schemas.py",
        root / "build_data/cities/schemas.py",
    ]
    return {path.relative_to(root).as_posix(): sha256(path) for path in sorted(files)}


def identity(snapshot: Snapshot, release: Row, shard_bytes: int) -> Row:
    return {
        "golden_sha256": snapshot.digest,
        "release": release,
        "implementation": implementation(),
        "shard_bytes": shard_bytes,
        "tools": {
            "python": platform.python_version(),
            "h3": h3.versions(),
            "pyarrow": pyarrow.__version__,
            "sqlite": sqlite3.sqlite_version,
            "zlib": zlib.ZLIB_RUNTIME_VERSION,
        },
    }


def manifest(
    snapshot: Snapshot,
    release: Row,
    export: Row,
    files: list[Row],
    count: int,
    coverage: str,
) -> Row:
    policy = snapshot.manifest["normalization"]["policy"]
    distant = integer(policy["distant_m"])
    cutoff = integer(policy["nearest_m"], 1)
    if distant >= cutoff:
        raise ValueError("Golden nearest-distance bands are inconsistent")
    return {
        "schema": "thereabouts-pack-1",
        "format": {"major": 1, "minor": 0, "required_features": 0},
        "family": "reverse",
        "minimum_reader": "0.1.0",
        "dependencies": [],
        "data_version": release["data_version"],
        "catalogue_epoch": release["catalogue_epoch"],
        "golden_sha256": snapshot.digest,
        "policy_sha256": digest(snapshot.manifest["normalization"]["policy"]),
        "nearest": {
            "distant_over_m": distant,
            "cutoff_m": cutoff,
            "exact_distance": False,
        },
        "export_fingerprint": digest(export),
        "export": export,
        "reference_resolution": 8,
        "block_resolution": 3,
        "h3_version": h3.__version__,
        "coverage": coverage,
        "place_count": count,
        "sources": release["sources"],
        "notices": [r["path"] for r in files if r["kind"] == "notice"],
        "files": files,
    }


def write_manifest(path: Path, value: Row) -> None:
    def validate(temporary: Path) -> None:
        parse(temporary.read_bytes())

    with atomic_output(path, validate) as temporary:
        temporary.write_bytes(canonical(value) + b"\n")

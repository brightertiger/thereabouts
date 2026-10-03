"""Export identities and canonical serving manifest publication."""

from pathlib import Path

import h3

from pipeline.pack_format.jsonio import canonical, digest, integer, parse
from pipeline.runtime.fingerprints import REPOSITORY, native_versions
from pipeline.runtime.fingerprints import identity as fingerprint
from pipeline.runtime.jsonio import atomic_output
from thereabouts.format import CELL_FORMAT_VERSION

from .snapshot import Row, Snapshot


def identity(snapshot: Snapshot, release: Row, shard_bytes: int) -> Row:
    code = fingerprint(
        [
            REPOSITORY / path
            for path in (
                "pipeline/engines/serving",
                "pipeline/engines/serving_codes",
                "pipeline/engines/cells/reader.py",
                "pipeline/engines/cells/schemas.py",
                "pipeline/engines/cities/schemas.py",
                "pipeline/sources/shared/lookup_schemas.py",
                "pipeline/pack_format",
                "pipeline/runtime/jsonio.py",
            )
        ],
        config={"shard_bytes": shard_bytes},
        pins={},
        native=native_versions(["h3", "pyarrow"], REPOSITORY / "uv.lock"),
        cell_format=CELL_FORMAT_VERSION,
    )
    return {
        "golden_sha256": snapshot.digest,
        "release": release,
        "implementation": {"pipeline": code},
        "shard_bytes": shard_bytes,
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

    with atomic_output(path) as temporary:
        temporary.write_bytes(canonical(value) + b"\n")
        validate(temporary)

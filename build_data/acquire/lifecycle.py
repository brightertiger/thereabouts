"""Source completion, verified resume and conservative removal of superseded work."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import read_json, verify_files
from .io import fingerprint
from .ledger import Ledger, read_units
from .manifests import MANIFEST_VERSION, inventory_path, load_manifest, publish_manifest
from .workspace import Workspace


def _cleanup_verified(
    workspace: Workspace, source: str, manifest: Mapping[str, Any]
) -> None:
    """Only called with a verified manifest while the caller owns the source lock."""
    root = workspace.normalized(source)
    current = {Path(record["path"]).resolve() for record in manifest["partitions"]}
    candidates = [
        path for path in root.rglob("*.parquet") if path.resolve() not in current
    ]
    # Interrupted atomic writes are expendable only once the whole source commits.
    candidates.extend(root.rglob("*.part"))
    work = workspace.work / source
    patterns = {
        "osm_land": (),
        "timezones": ("shapes/*.shp", "shapes/*.shx", "shapes/*.dbf", "shapes/*.prj"),
        "overture": ("entities.sqlite3", "entities.sqlite3-journal"),
        "geonames": (
            "extracted/*/allCountries.txt",
            "extracted/*/alternateNamesV2.txt",
            "*/lookup.sqlite3",
            "*/lookup.sqlite3.part",
            "*/lookup.sqlite3.part-journal",
        ),
        "geoboundaries": ("*/layer.shp", "*/layer.shx", "*/layer.dbf", "*/layer.prj"),
    }
    for pattern in patterns.get(source, ()):
        candidates.extend(work.glob(pattern))
    protected = {
        Path(record["path"]).resolve()
        for record in [
            *manifest["auxiliary"],
            *manifest["inputs"],
            manifest["inventory"],
        ]
    }
    removed_bytes = 0
    removed = 0
    for path in candidates:
        resolved = path.resolve()
        if resolved in protected or resolved in current or path.is_symlink():
            continue
        if not (
            resolved.is_relative_to(root.resolve())
            or resolved.is_relative_to(work.resolve())
        ):
            raise ValueError(f"Cleanup path escapes source directories: {path}")
        if path.is_file():
            removed_bytes += path.stat().st_size
            path.unlink()
            removed += 1
    # Remove empty directories, preserving roots, all logs and verification reports.
    for directory in (root, work):
        for path in sorted(
            directory.rglob("*"), key=lambda p: len(p.parts), reverse=True
        ):
            if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                path.rmdir()
    if removed:
        print(
            f"{source}: pruned {removed} superseded files ({removed_bytes:,} bytes)",
            flush=True,
        )


def prune_source(workspace: Workspace, source: str) -> None:
    """Verify before deletion; caller must hold the source's single_run lock."""
    _cleanup_verified(workspace, source, load_manifest(workspace, source))


def resume_source(
    workspace: Workspace, source: str, configuration: Mapping[str, object]
) -> bool:
    """Skip preprocessing too when current inputs, policy and every output verify.

    Legacy manifests take the ordinary per-unit resume path once, preserving their
    fingerprints. Publication upgrades their metadata without rewriting Parquet.
    """
    path = workspace.normalized(source) / "manifest.json"
    if not path.exists():
        return False
    try:
        if read_json(path).get("configuration") != configuration:
            return False
        manifest = load_manifest(workspace, source)
    except (OSError, ValueError, KeyError):
        return False
    _cleanup_verified(workspace, source, manifest)
    print(f"{source}: verified complete; no work", flush=True)
    return True


def resume_download(workspace: Workspace, source: str) -> bool:
    """Verify a completed source's raw inputs without rewriting download reports."""
    path = workspace.normalized(source) / "manifest.json"
    if not path.exists():
        return False
    try:
        manifest = read_json(path)
        if (
            manifest.get("manifest_version") != MANIFEST_VERSION
            or Path(manifest["inventory"]["path"])
            != inventory_path(workspace, source).resolve()
            or not Ledger(workspace.ledger_path).is_complete(
                f"{source}.manifest", "current", fingerprint(manifest)
            )
        ):
            return False
        verify_files([manifest["inventory"], *manifest["inputs"]])
    except (OSError, ValueError, KeyError):
        return False
    print(f"{source}: verified downloaded; no work", flush=True)
    return True


def finish_source(
    workspace: Workspace,
    source: str,
    release: str,
    units: Sequence[Mapping[str, Any]],
    auxiliary: Sequence[Path],
    configuration: Mapping[str, object],
    *,
    inputs: Sequence[Path] = (),
) -> None:
    raw_inputs = list(inputs)
    for record in read_units(workspace.ledger_path, f"{source}.download"):
        raw_inputs.extend(Path(output["path"]) for output in record["outputs"])
    publish_manifest(
        workspace, source, release, units, auxiliary, configuration, inputs=raw_inputs
    )
    prune_source(workspace, source)

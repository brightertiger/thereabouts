"""Deterministic zstd-compressed client archives and the format-3 release index.

The archive codec, the transport caps and the index format are defined once in the
Rust core and read here through ``thereabouts._core``; clients enforce the same values.
"""

import importlib
import json
from pathlib import Path
from typing import Any, cast

from pipeline.engines.artifacts import read_json
from pipeline.runtime.jsonio import atomic_output, sha256_file
from pipeline.runtime.paths import located
from pipeline.runtime.resources import ResourceGuard

TAR_BLOCK = 512
Row = dict[str, Any]


def transport() -> Any:
    try:
        return importlib.import_module("thereabouts._core")
    except ImportError as error:
        raise ValueError(
            "Client archives require the merged Rust client (thereabouts._core)"
        ) from error


def _codec(action: Any, *args: str) -> Row:
    """Archive refusals from the Rust codec are release validation failures."""
    from thereabouts.errors import GeocoderError

    try:
        return cast(Row, action(*args))
    except GeocoderError as error:
        raise ValueError(f"Release archive refused: {error}") from error


def members(pack: Path) -> list[Row]:
    """Every manifest file plus manifest.json itself, with size and digest."""
    manifest = read_json(pack / "manifest.json")
    saved = pack / "manifest.json"
    return [
        *manifest["files"],
        {
            "path": "manifest.json",
            "size": saved.stat().st_size,
            "sha256": sha256_file(saved),
        },
    ]


def archive(pack: Path, guard: ResourceGuard) -> Path:
    core = transport()
    rows = members(pack)
    # The plain ustar stream bounds the compressed archive; admit it before writing.
    estimate = (
        sum(
            (located(pack, row["path"]).stat().st_size + TAR_BLOCK - 1)
            // TAR_BLOCK
            * TAR_BLOCK
            + TAR_BLOCK
            for row in rows
        )
        + 2 * TAR_BLOCK
    )
    if estimate > core.MAX_UNPACKED_BYTES:
        raise ValueError("Client archive exceeds the unpacked size cap")
    target = pack.with_name(pack.name + core.ARCHIVE_SUFFIX)
    if target.exists():
        verify_archive(target, rows)
        return target
    guard.admit(estimate)
    try:
        with atomic_output(target) as temporary:
            _codec(core.archive_pack, str(pack), str(temporary))
            verify_archive(temporary, rows)
    finally:
        guard.release(
            estimate, written_bytes=target.stat().st_size if target.exists() else 0
        )
    return target


def verify_archive(path: Path, rows: list[Row]) -> int:
    """The archive holds exactly the pack inventory; returns its unpacked size."""
    core = transport()
    if path.stat().st_size > core.MAX_ARCHIVE_BYTES:
        raise ValueError("Client archive exceeds the compressed size cap")
    summary = _codec(core.inspect_archive, str(path))
    expected = {row["path"]: (row["size"], row["sha256"]) for row in rows}
    found = {row["path"]: (row["size"], row["sha256"]) for row in summary["files"]}
    if found != expected or len(summary["files"]) != len(found):
        raise ValueError(f"Release archive differs from its pack: {path.name}")
    return int(summary["unpacked_size"])


def index(root: Path, version: str, families: list[str]) -> Path:
    core = transport()
    packs = {}
    for family in sorted(families):
        pack = root / family
        path = root / f"{family}{core.ARCHIVE_SUFFIX}"
        packs[family] = {
            "url": path.name,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
            "unpacked_size": verify_archive(path, members(pack)),
            "format_minor": read_json(pack / "manifest.json")["format_minor"],
        }
    value = {"format": core.INDEX_FORMAT, "datasets": {version: {"packs": packs}}}
    target = root / "index.json"
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    if target.exists():
        if target.read_text() != encoded:
            raise ValueError("Release index is immutable; choose a new dataset version")
    else:
        with atomic_output(target) as temporary:
            temporary.write_text(encoded)
    return target


def merge(existing: Row | None, version: str, current: Row) -> Row:
    """Add one version's index to the aggregate ``packs/index.json``.

    Archive URLs become relative to the aggregate (``<version>/<family>.tar.zst``).
    Other versions and unknown fields are kept; a listed version must not change.
    """
    form = transport().INDEX_FORMAT
    if current.get("format") != form or set(current.get("datasets", {})) != {version}:
        raise ValueError("A release index must list exactly its own version")
    entry = {
        "packs": {
            family: {**pack, "url": f"{version}/{pack['url']}"}
            for family, pack in sorted(current["datasets"][version]["packs"].items())
        }
    }
    result: Row = {"format": form, "datasets": {}}
    if existing is not None:
        if existing.get("format") != form or not isinstance(
            existing.get("datasets"), dict
        ):
            raise ValueError(f"Aggregate release index is not format {form}")
        result = {**existing, "datasets": dict(existing["datasets"])}
    previous = result["datasets"].get(version)
    if previous is not None and previous.get("packs") != entry["packs"]:
        raise ValueError(f"Aggregate release index already lists another {version}")
    result["datasets"][version] = previous or entry
    return result


def encode(value: Row) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()

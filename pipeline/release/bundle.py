"""Deterministic local client archives and the format-2 release index."""

import json
import tarfile
from pathlib import Path
from typing import Any

from pipeline.engines.artifacts import read_json
from pipeline.runtime.jsonio import atomic_output, sha256_file
from pipeline.runtime.paths import located
from pipeline.runtime.resources import ResourceGuard

# The client admits at most 1 GiB per archive. Reserve the complete uncompressed
# tar plus its headers before writing, and keep each archive independent.
MAX_ARCHIVE_BYTES = 1024**3
TAR_BLOCK = 512


def archive(pack: Path, guard: ResourceGuard) -> Path:
    manifest = read_json(pack / "manifest.json")
    records = [*manifest["files"], {"path": "manifest.json"}]
    paths = [located(pack, row["path"]) for row in records]
    estimate = sum(
        (p.stat().st_size + TAR_BLOCK - 1) // TAR_BLOCK * TAR_BLOCK + TAR_BLOCK
        for p in paths
    )
    estimate = (
        (estimate + 1024 + tarfile.RECORDSIZE - 1)
        // tarfile.RECORDSIZE
        * tarfile.RECORDSIZE
    )
    if estimate > MAX_ARCHIVE_BYTES:
        raise ValueError("Client archive exceeds the 1 GiB admission limit")
    target = pack.with_suffix(".tar")
    if target.exists():
        verify_archive(target, pack, records)
        return target
    guard.admit(estimate)
    try:
        with atomic_output(target) as temporary:
            with tarfile.open(temporary, "w", format=tarfile.USTAR_FORMAT) as stream:
                for row, path in sorted(
                    zip(records, paths, strict=True), key=lambda item: item[0]["path"]
                ):
                    header = tarfile.TarInfo(row["path"])
                    header.size = path.stat().st_size
                    header.mode = 0o644
                    with path.open("rb") as data:
                        stream.addfile(header, data)
            verify_archive(temporary, pack, records)
    finally:
        guard.release(
            estimate, written_bytes=target.stat().st_size if target.exists() else 0
        )
    return target


def verify_archive(path: Path, pack: Path, records: list[dict[str, Any]]) -> None:
    import hashlib

    expected = {row["path"]: located(pack, row["path"]) for row in records}
    with tarfile.open(path, "r:") as stream:
        seen = set()
        for member in stream:
            if (
                not member.isfile()
                or member.name not in expected
                or member.name in seen
            ):
                raise ValueError(f"Invalid release archive member: {member.name}")
            source = expected[member.name]
            data = stream.extractfile(member)
            if data is None:
                raise ValueError("Missing release archive payload")
            with data:
                hasher = hashlib.sha256()
                while chunk := data.read(1024 * 1024):
                    hasher.update(chunk)
                digest = hasher.hexdigest()
            expected_row = next(row for row in records if row["path"] == member.name)
            expected_digest = expected_row.get("sha256", sha256_file(source))
            if (
                member.size != source.stat().st_size
                or digest != sha256_file(source)
                or digest != expected_digest
            ):
                raise ValueError(f"Release archive checksum mismatch: {member.name}")
            seen.add(member.name)
        if seen != expected.keys():
            raise ValueError("Incomplete release archive")


def index(root: Path, version: str, families: list[str]) -> Path:
    packs = {}
    for family in sorted(families):
        pack = root / family
        manifest = read_json(pack / "manifest.json")
        path = root / f"{family}.tar"
        verify_archive(path, pack, [*manifest["files"], {"path": "manifest.json"}])
        packs[family] = {
            "url": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "format_minor": manifest["format_minor"],
        }
    value = {"format": 2, "datasets": {version: {"packs": packs}}}
    target = root / "index.json"
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    if target.exists():
        if target.read_text() != encoded:
            raise ValueError("Release index is immutable; choose a new dataset version")
    else:
        with atomic_output(target) as temporary:
            temporary.write_text(encoded)
    return target

"""Idempotent, checksum-verified fsspec publication with a final success receipt."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fsspec

from pipeline.config.release import PublishSettings
from pipeline.engines.artifacts import read_json
from pipeline.runtime.jsonio import encode, sha256_file
from pipeline.runtime.paths import located
from pipeline.runtime.records import Output

from .source import Row
from .verify import verify_dataset


@dataclass(frozen=True)
class Upload:
    local: Path
    remote: str
    size: int
    sha256: str


def inventory(dataset: Path, packs: dict[str, Path], version: str) -> list[Upload]:
    manifest = verify_dataset(dataset)
    entries = []
    for prefix, root, records in [
        (f"dataset/{version}", dataset, manifest["files"]),
        *[
            (
                f"packs/{version}/{family}",
                directory,
                read_json(directory / "manifest.json")["files"],
            )
            for family, directory in sorted(packs.items())
        ],
    ]:
        files = [
            *records,
            {
                "path": "manifest.json",
                "size": (root / "manifest.json").stat().st_size,
                "sha256": sha256_file(root / "manifest.json"),
            },
        ]
        seen = set()
        for record in files:
            output = Output(record["path"], record["size"], record["sha256"])
            if output.path in seen:
                raise ValueError(f"Duplicate publication path: {output.path}")
            seen.add(output.path)
            path = located(root, output.path)
            if path.stat().st_size != output.size or sha256_file(path) != output.sha256:
                raise ValueError(f"Local publication input changed: {output.path}")
            entries.append(
                Upload(path, f"{prefix}/{output.path}", output.size, output.sha256)
            )
    if packs:
        roots = {path.parent for path in packs.values()}
        if len(roots) != 1:
            raise ValueError("Client packs must share one release directory")
        root = next(iter(roots))
        index = read_json(root / "index.json")
        records = index["datasets"][version]["packs"]
        if set(records) != set(packs):
            raise ValueError("Release index differs from requested families")
        for record in records.values():
            path = located(root, record["url"])
            if (
                path.stat().st_size != record["bytes"]
                or sha256_file(path) != record["sha256"]
            ):
                raise ValueError("Client archive checksum mismatch")
            entries.append(
                Upload(
                    path,
                    f"packs/{version}/{path.name}",
                    record["bytes"],
                    record["sha256"],
                )
            )
        path = root / "index.json"
        entries.append(
            Upload(
                path,
                f"packs/{version}/index.json",
                path.stat().st_size,
                sha256_file(path),
            )
        )
    return entries


def remote_hash(fs: Any, path: str, read_bytes: int) -> str:
    value = hashlib.sha256()
    with fs.open(path, "rb") as stream:
        while chunk := stream.read(read_bytes):
            value.update(chunk)
    return value.hexdigest()


def publish(
    entries: list[Upload],
    destination: str,
    version: str,
    settings: PublishSettings,
    *,
    dry_run: bool,
) -> Row:
    fs, base = fsspec.core.url_to_fs(destination)
    prefix = base.rstrip("/")
    records = [
        {"path": item.remote, "size": item.size, "sha256": item.sha256}
        for item in entries
    ]
    receipt = encode({"version": version, "files": records}) + b"\n"
    marker = f"{prefix}/{version}/_SUCCESS"
    if fs.exists(marker):
        with fs.open(marker, "rb") as stream:
            if stream.read() != receipt:
                raise ValueError("Published version already has a different inventory")
    actions = []
    for entry in entries:
        path = f"{prefix}/{entry.remote}"
        present = fs.exists(path)
        if present and (
            fs.size(path) != entry.size
            or remote_hash(fs, path, settings.read_bytes) != entry.sha256
        ):
            raise ValueError(f"Conflicting object in immutable release: {entry.remote}")
        actions.append((entry, path, present))
    # All conflicts are checked before the first upload.
    for entry, path, present in actions:
        if present or dry_run:
            continue
        fs.makedirs(path.rpartition("/")[0], exist_ok=True)
        actual = hashlib.sha256()
        with fs.transaction:
            with (
                entry.local.open("rb") as source,
                fs.open(path, "wb", block_size=settings.multipart_bytes) as target,
            ):
                while chunk := source.read(settings.read_bytes):
                    actual.update(chunk)
                    target.write(chunk)
            if actual.hexdigest() != entry.sha256:
                raise ValueError(f"Local upload checksum differs: {entry.remote}")
        if (
            actual.hexdigest() != entry.sha256
            or fs.size(path) != entry.size
            or remote_hash(fs, path, settings.read_bytes) != entry.sha256
        ):
            raise ValueError(f"Uploaded checksum differs: {entry.remote}")
    if not dry_run:
        # Recheck skipped objects too: no success marker follows a concurrent change.
        for entry, path, _ in actions:
            if (
                fs.size(path) != entry.size
                or remote_hash(fs, path, settings.read_bytes) != entry.sha256
            ):
                raise ValueError(
                    f"Publication changed before completion: {entry.remote}"
                )
        if not fs.exists(marker):
            fs.makedirs(marker.rpartition("/")[0], exist_ok=True)
            with fs.transaction, fs.open(marker, "wb") as target:
                target.write(receipt)
        if (
            remote_hash(fs, marker, settings.read_bytes)
            != hashlib.sha256(receipt).hexdigest()
        ):
            raise ValueError("Success receipt checksum differs")
    return {
        "version": version,
        "dry_run": dry_run,
        "upload": sum(not present for _, _, present in actions),
        "skip": sum(present for _, _, present in actions),
        "bytes": sum(entry.size for entry, _, present in actions if not present),
        "success_path": f"{version}/_SUCCESS",
        "files": records,
    }

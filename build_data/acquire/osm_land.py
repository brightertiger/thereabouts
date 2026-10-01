"""Pinned, resumable split WGS84 OSM land acquisition and normalization."""

from __future__ import annotations

import fcntl
import json
import shutil
import sqlite3
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any, cast

from . import Ledger, Workspace, atomic_output, download_file, fingerprint, sha256_file
from .io import write_json

SOURCE = "osm_land"
ARCHIVE = "land-polygons-split-4326.zip"
SOURCE_URL = f"https://osmdata.openstreetmap.de/download/{ARCHIVE}"
LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
RELEASE = "2026-10-01T03:37:19Z"
EXPECTED_SIZE = 927_857_432
ETAG = '"374dfb18-65cbf220083e3"'
LAST_MODIFIED = "Thu, 01 Oct 2026 03:37:19 GMT"
SOURCE_BUDGET = 8_000_000_000
BUILDER_VERSION = "osm-land-1"
POLICY_VERSION = "preserve-all-split-land-1"
COPY_BYTES = 1024 * 1024
LEDGER_RETRY_SECONDS = 30


def _ledger(workspace: Workspace) -> Ledger:
    """Work around the shared layer's concurrent WAL-initialization race."""
    deadline = time.monotonic() + LEDGER_RETRY_SECONDS
    while True:
        try:
            return Ledger(workspace.ledger_path)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


@contextmanager
def _source_lock(workspace: Workspace) -> Iterator[None]:
    workspace.work.mkdir(parents=True, exist_ok=True)
    with (workspace.work / "osm_land.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another osm_land process owns the source lock") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _budget(workspace: Workspace, required_bytes: int = 0) -> None:
    workspace.check_budget(required_bytes)
    roots = (workspace.raw(SOURCE), workspace.normalized(SOURCE))
    used = sum(
        p.stat().st_size for root in roots for p in root.rglob("*") if p.is_file()
    )
    used += sum(
        p.stat().st_size for p in workspace.work.glob("osm_land*") if p.is_file()
    )
    if used + required_bytes > SOURCE_BUDGET:
        raise OSError("OSM land would exceed its 8 GB source budget")


def _inventory(workspace: Workspace) -> dict[str, Any]:
    path = workspace.raw(SOURCE) / "inventory.json"
    if path.exists():
        inventory = cast(dict[str, Any], json.loads(path.read_text()))
        if (
            inventory["source_release"],
            inventory["size"],
            inventory["etag"],
            inventory["source_url"],
            inventory["last_modified"],
        ) != (
            RELEASE,
            EXPECTED_SIZE,
            ETAG,
            SOURCE_URL,
            LAST_MODIFIED,
        ):
            raise ValueError("Inventory differs from the explicit pinned OSM release")
        return inventory
    inventory = {
        "source": SOURCE,
        "source_url": SOURCE_URL,
        "resolved_url": SOURCE_URL,
        "source_release": RELEASE,
        "size": EXPECTED_SIZE,
        "etag": ETAG,
        "last_modified": LAST_MODIFIED,
        "publisher_sha256": None,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "license": "ODbL-1.0",
        "license_url": LICENSE_URL,
        "attribution": (
            "© OpenStreetMap contributors; coastline service osmdata.openstreetmap.de"
        ),
    }
    write_json(path, inventory)
    return inventory


def _snapshot(workspace: Workspace) -> Path:
    return workspace.raw(SOURCE) / RELEASE.replace(":", "")


def _member_path(snapshot: Path, member: zipfile.ZipInfo) -> Path:
    relative = PurePosixPath(member.filename)
    if relative.is_absolute() or ".." in relative.parts or "\\" in member.filename:
        raise ValueError(f"Unsafe ZIP member: {member.filename}")
    if (member.external_attr >> 16) & 0o170000 == 0o120000:
        raise ValueError(f"Symlink ZIP member: {member.filename}")
    return snapshot / "extracted" / relative


def _verify_size(path: Path, expected: int) -> None:
    if path.stat().st_size != expected:
        raise ValueError(f"Incorrect extracted size: {path}")


def _extract(
    workspace: Workspace, archive: Path, checksum: str, ledger: Ledger
) -> None:
    with zipfile.ZipFile(archive) as source:
        members = [member for member in source.infolist() if not member.is_dir()]
        if len({member.filename for member in members}) != len(members):
            raise ValueError("Duplicate ZIP member names")
        for member in members:
            target = _member_path(archive.parent, member)
            unit_id = f"extract/{member.filename}"
            inputs_hash = fingerprint(
                {
                    "archive_sha256": checksum,
                    "member": member.filename,
                    "crc32": member.CRC,
                    "size": member.file_size,
                    "builder": BUILDER_VERSION,
                }
            )
            if ledger.is_complete(f"{SOURCE}.download", unit_id, inputs_hash):
                continue
            _budget(workspace, member.file_size)
            with (
                atomic_output(
                    target, partial(_verify_size, expected=member.file_size)
                ) as temp,
                source.open(member) as reader,
                temp.open("wb") as writer,
            ):
                # ZipExtFile verifies the member CRC when EOF is reached.
                shutil.copyfileobj(reader, writer, COPY_BYTES)
            ledger.complete(
                f"{SOURCE}.download",
                unit_id,
                inputs_hash,
                [target],
                metadata={
                    "zip_crc32_verified": member.CRC,
                    "bytes": member.file_size,
                },
            )
            print(
                f"Extracted {member.filename}: {member.file_size:,} bytes", flush=True
            )


def download(workspace: Workspace) -> None:
    """Download the plan's immutable pin and CRC-check/extract each ZIP member."""
    started = time.monotonic()
    with _source_lock(workspace):
        inventory = _inventory(workspace)
        archive = _snapshot(workspace) / ARCHIVE
        partial = archive.with_name(ARCHIVE + ".part")
        remaining = (
            0
            if archive.exists()
            else EXPECTED_SIZE - (partial.stat().st_size if partial.exists() else 0)
        )
        _budget(workspace, max(0, remaining))
        print(f"Downloading pinned {SOURCE_URL}, {EXPECTED_SIZE:,} bytes", flush=True)
        download_file(
            SOURCE_URL,
            archive,
            expected_size=EXPECTED_SIZE,
            etag=ETAG,
            last_modified=LAST_MODIFIED,
            retries=30,
            timeout=60,
        )
        checksum = sha256_file(archive)
        ledger = _ledger(workspace)
        inputs_hash = fingerprint(
            {
                "inventory": inventory,
                "sha256": checksum,
                "builder": BUILDER_VERSION,
            }
        )
        _extract(workspace, archive, checksum, ledger)
        report = archive.parent / "download-verification.json"
        if not ledger.is_complete(f"{SOURCE}.download", ARCHIVE, inputs_hash):
            with zipfile.ZipFile(archive) as source:
                members = [
                    {"name": m.filename, "size": m.file_size, "crc32": m.CRC}
                    for m in source.infolist()
                    if not m.is_dir()
                ]
            write_json(
                report,
                {
                    "archive_sha256": checksum,
                    "archive_bytes": archive.stat().st_size,
                    "zip_members": members,
                    "all_member_crc_verified": True,
                    "elapsed_seconds": time.monotonic() - started,
                },
            )
            ledger.complete(
                f"{SOURCE}.download",
                ARCHIVE,
                inputs_hash,
                [archive, report],
                metadata={"zip_crc_verified": True},
            )
        print(
            "OSM land download/extraction complete in "
            f"{time.monotonic() - started:.1f}s",
            flush=True,
        )


def normalize(workspace: Workspace) -> None:
    """Publish verified bounded areas partitions, skipping completed SHX units."""
    from .osm_land_normalize import normalize as normalize_land

    normalize_land(workspace)

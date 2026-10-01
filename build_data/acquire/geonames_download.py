"""Pinned, restartable GeoNames downloads; independent of normalization."""

from __future__ import annotations

import fcntl
import json
import time
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.client import HTTPException, HTTPResponse
from pathlib import Path
from typing import cast

from . import Ledger, Workspace, download_file, fingerprint, sha256_file
from .download import RemoteChangedError
from .io import write_json

SOURCE = "geonames"
BASE_URL = "https://download.geonames.org/export/dump/"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
FILES = (
    "allCountries.zip",
    "alternateNamesV2.zip",
    "countryInfo.txt",
    "admin1CodesASCII.txt",
    "admin2Codes.txt",
    "featureCodes_en.txt",
    "readme.txt",
)
BUDGET_BYTES = 10_000_000_000


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


@contextmanager
def source_lock(workspace: Workspace, stage: str) -> Iterator[None]:
    workspace.work.mkdir(parents=True, exist_ok=True)
    with (workspace.work / f"geonames-{stage}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"GeoNames {stage} already running") from error
        yield


def budget(workspace: Workspace, required: int = 0) -> None:
    workspace.check_budget(required)
    roots = [workspace.raw(SOURCE), workspace.normalized(SOURCE)]
    roots.extend(workspace.work.glob("geonames*"))
    used = 0
    for root in roots:
        for path in root.rglob("*") if root.is_dir() else [root]:
            if path.is_file():
                used += path.stat().st_size
    if used + required > BUDGET_BYTES:
        raise OSError("GeoNames would exceed its 10 GB disk budget")


def _probe(url: str) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept-Encoding": "identity",
            "User-Agent": "PyOfflineGeocoder/acquire",
        },
        method="HEAD",
    )
    with cast(HTTPResponse, urllib.request.urlopen(request, timeout=60)) as response:
        size = int(response.getheader("Content-Length", "0"))
        etag = response.getheader("ETag")
        modified = response.getheader("Last-Modified")
        resolved = response.geturl()
    if size <= 0 or not (etag or modified):
        raise ValueError(f"Missing size or validator for {url}")
    if etag and etag.startswith("W/"):
        etag = None
    if not (etag or modified):
        raise ValueError(f"No usable validator for {url}")
    headers = {
        "Accept-Encoding": "identity",
        "Range": "bytes=0-0",
        "If-Range": etag or modified or "",
    }
    with cast(
        HTTPResponse,
        urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=60
        ),
    ) as response:
        if (
            response.status != 206
            or response.getheader("Content-Range") != f"bytes 0-0/{size}"
        ):
            raise ValueError(f"No demonstrated resumable route for {url}")
        if (etag and response.getheader("ETag") != etag) or (
            not etag and response.getheader("Last-Modified") != modified
        ):
            raise RemoteChangedError(f"Validator changed during probe: {url}")
        if len(response.read(2)) != 1:
            raise ValueError("Range probe length mismatch")
    return {
        "url": url,
        "resolved_url": resolved,
        "size": size,
        "etag": etag,
        "last_modified": modified,
        "retrieved_at": now(),
        "license": "CC-BY-4.0",
        "license_url": LICENSE_URL,
        "range_verified": True,
    }


def probe(url: str) -> dict[str, object]:
    for attempt in range(12):
        try:
            return _probe(url)
        except (OSError, HTTPException, RemoteChangedError):
            if attempt == 11:
                raise
            time.sleep(min(60, 2**attempt))
    raise AssertionError("unreachable")


def _verify_archive(path: Path) -> dict[str, object]:
    if path.suffix != ".zip":
        # Decode incrementally, including all support tables and the licence notice.
        with path.open(encoding="utf-8") as stream:
            lines = sum(1 for _ in stream)
        return {"utf8_lines": lines}
    with zipfile.ZipFile(path) as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise ValueError(f"ZIP CRC failure: {corrupt}")
        return {
            "zip_crc_valid": True,
            "members": [
                {"name": item.filename, "size": item.file_size, "crc32": item.CRC}
                for item in archive.infolist()
                if not item.is_dir()
            ],
        }


def _download_one(
    workspace: Workspace, inventory: dict[str, object], name: str
) -> None:
    root = workspace.raw(SOURCE)
    files = cast(dict[str, dict[str, object]], inventory["files"])
    ledger = Ledger(workspace.ledger_path)
    for _ in range(8):
        if name not in files:
            pin = probe(BASE_URL + name)
            pin["path"] = str(
                root / str(inventory["source_release"]) / fingerprint(pin) / name
            )
            files[name] = pin
            write_json(root / "inventory.json", inventory)
        pin = files[name]
        path = Path(str(pin["path"]))
        inputs_hash = fingerprint(
            {
                k: v
                for k, v in pin.items()
                if k not in ("sha256", "verification", "completed_at", "seconds")
            }
        )
        if ledger.is_complete("geonames.download", name, inputs_hash):
            print(f"Verified cached {name}", flush=True)
            return
        budget(
            workspace,
            max(
                0,
                int(str(pin["size"]))
                - (
                    path.with_name(name + ".part").stat().st_size
                    if path.with_name(name + ".part").exists()
                    else 0
                ),
            ),
        )
        started = time.monotonic()
        print(
            f"Downloading {name}: {pin['size']} bytes, "
            f"{pin['etag'] or pin['last_modified']}",
            flush=True,
        )
        try:
            download_file(
                str(pin["url"]),
                path,
                expected_size=int(str(pin["size"])),
                etag=cast(str | None, pin["etag"]),
                last_modified=cast(str | None, pin["last_modified"]),
                retries=60,
                timeout=60,
                backoff=2,
            )
        except RemoteChangedError:
            if path.exists():
                raise
            history = cast(list[object], inventory.setdefault("superseded", []))
            history.append({**pin, "superseded_at": now()})
            path.with_name(name + ".part").unlink(missing_ok=True)
            del files[name]
            write_json(root / "inventory.json", inventory)
            print(f"Remote changed: restarting {name} with a fresh pin", flush=True)
            continue
        pin["sha256"] = sha256_file(path)
        pin["verification"] = _verify_archive(path)
        pin["completed_at"] = now()
        pin["seconds"] = round(time.monotonic() - started, 3)
        write_json(root / "inventory.json", inventory)
        ledger.complete(
            "geonames.download",
            name,
            inputs_hash,
            [path, path.with_name(name + ".download.json")],
            metadata=pin,
        )
        print(
            f"Completed {name}: sha256={pin['sha256']} in {pin['seconds']}s", flush=True
        )
        return
    raise RuntimeError(f"Too many mutable snapshots while downloading {name}")


def download(workspace: Workspace) -> None:
    """Acquire once, resume pinned bytes, and rotate changed partial daily objects."""
    with source_lock(workspace, "download"):
        root = workspace.raw(SOURCE)
        root.mkdir(parents=True, exist_ok=True)
        inventory_path = root / "inventory.json"
        inventory = (
            read_json(inventory_path)
            if inventory_path.exists()
            else {
                "source": SOURCE,
                "source_release": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
                "started_at": now(),
                "files": {},
                "publisher_sha256": None,
            }
        )
        for name in FILES:
            _download_one(workspace, inventory, name)
        inventory.setdefault("completed_at", now())
        write_json(inventory_path, inventory)
        from .geonames_statistics import download_statistics

        download_statistics(workspace)
        print("GeoNames download complete", flush=True)

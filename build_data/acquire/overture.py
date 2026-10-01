"""Pinned, resumable Overture division and division-area acquisition."""

from __future__ import annotations

import fcntl
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.client import HTTPException, HTTPResponse
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq

from . import Ledger, Workspace, download_file, fingerprint
from .io import write_json

SOURCE = "overture"
BUCKET = "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com"
LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
ATTRIBUTION_URL = "https://docs.overturemaps.org/attribution/"
RELEASE_NOTES_URL = "https://docs.overturemaps.org/blog/2026/09/23/release-notes/"
PUBLISHED_COUNTS = {"2026-09-23.1": {"division": 4_688_229, "division_area": 1_080_667}}
SOURCE_LIMIT = 25_000_000_000
VERSION = "overture-acquire-1"
TYPES = ("division", "division_area")
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


def _request(url: str, headers: dict[str, str] | None = None) -> HTTPResponse:
    request = urllib.request.Request(url, headers=headers or {})
    return cast(HTTPResponse, urllib.request.urlopen(request, timeout=60))


def _fetch(url: str) -> bytes:
    for attempt in range(6):
        try:
            with _request(url) as response:
                return response.read()
        except (OSError, HTTPException):
            if attempt == 5:
                raise
            time.sleep(min(2**attempt, 30))
    raise AssertionError("unreachable")


def _listing(prefix: str, delimiter: str | None = None) -> list[ET.Element]:
    pages: list[ET.Element] = []
    query = {"list-type": "2", "prefix": prefix}
    if delimiter:
        query["delimiter"] = delimiter
    while True:
        page = ET.fromstring(_fetch(BUCKET + "/?" + urllib.parse.urlencode(query)))
        pages.append(page)
        if page.findtext("s3:IsTruncated", namespaces=NS) != "true":
            return pages
        token = page.findtext("s3:NextContinuationToken", namespaces=NS)
        if not token:
            raise ValueError("Truncated S3 listing without continuation token")
        query["continuation-token"] = token


def _range_probe(obj: dict[str, Any]) -> None:
    with _request(
        obj["url"],
        {"Range": "bytes=0-3", "If-Match": obj["etag"], "Accept-Encoding": "identity"},
    ) as response:
        if (
            response.status != 206
            or response.getheader("Content-Range") != f"bytes 0-3/{obj['size']}"
            or response.getheader("ETag") != obj["etag"]
            or response.read() != b"PAR1"
        ):
            raise ValueError(f"Parquet range probe failed: {obj['key']}")
        obj["resolved_url"] = response.geturl()
        obj["last_modified"] = response.getheader("Last-Modified")
        obj["range_verified"] = True


def _inventory(workspace: Workspace) -> dict[str, Any]:
    path = workspace.raw(SOURCE) / "inventory.json"
    if path.exists():
        return cast(dict[str, Any], json.loads(path.read_text()))
    releases = [
        node.text.split("/")[1]
        for page in _listing("release/", "/")
        for node in page.findall("s3:CommonPrefixes/s3:Prefix", NS)
        if node.text
    ]
    release = max(releases)
    root = workspace.raw(SOURCE) / release
    root.mkdir(parents=True, exist_ok=True)
    objects: list[dict[str, Any]] = []
    for kind in TYPES:
        for number, page in enumerate(
            _listing(f"release/{release}/theme=divisions/type={kind}/")
        ):
            (root / f"listing-{kind}-{number}.xml").write_bytes(ET.tostring(page))
            for node in page.findall("s3:Contents", NS):
                key = node.findtext("s3:Key", namespaces=NS)
                if not key or not key.endswith(".parquet"):
                    continue
                obj: dict[str, Any] = {
                    "key": key,
                    "type": kind,
                    "size": int(node.findtext("s3:Size", "0", NS)),
                    "etag": node.findtext("s3:ETag", namespaces=NS),
                    "listed_last_modified": node.findtext(
                        "s3:LastModified", namespaces=NS
                    ),
                    "url": BUCKET + "/" + urllib.parse.quote(key, safe="/="),
                    "relative_path": f"{release}/{kind}/{Path(key).name}",
                }
                _range_probe(obj)
                objects.append(obj)
    if set(obj["type"] for obj in objects) != set(TYPES):
        raise ValueError("Release is missing required object types")
    inventory: dict[str, Any] = {
        "source": SOURCE,
        "source_release": release,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "objects": sorted(objects, key=lambda obj: obj["key"]),
        "license": "ODbL-1.0",
        "license_url": LICENSE_URL,
        "attribution_url": ATTRIBUTION_URL,
        "publisher_sha256": None,
    }
    (root / "attribution.html").write_bytes(_fetch(ATTRIBUTION_URL))
    write_json(root / "inventory.json", inventory)
    write_json(path, inventory)
    return inventory


def _budget(workspace: Workspace, required: int = 0) -> None:
    workspace.check_budget(required)
    used = sum(
        path.stat().st_size
        for root in (
            workspace.raw(SOURCE),
            workspace.normalized(SOURCE),
            workspace.work / SOURCE,
        )
        if root.exists()
        for path in root.rglob("*")
        if path.is_file()
    )
    if used + required > SOURCE_LIMIT:
        raise OSError("Overture would exceed its 25 GB disk budget")


@contextmanager
def _lock(workspace: Workspace, stage: str) -> Iterator[None]:
    workspace.work.mkdir(parents=True, exist_ok=True)
    with (workspace.work / f"overture-{stage}.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"Overture {stage} is already running") from error
        yield


def download(workspace: Workspace) -> None:
    """Download one whole immutable Parquet object per verified ledger unit."""
    started = time.monotonic()
    with _lock(workspace, "download"):
        inventory = _inventory(workspace)
        ledger = Ledger(workspace.ledger_path)
        print(
            f"Pinned {inventory['source_release']}: "
            f"{len(inventory['objects'])} objects",
            flush=True,
        )
        counts: dict[str, int] = {}
        for obj in inventory["objects"]:
            inputs_hash = fingerprint({"object": obj, "version": VERSION})
            destination = workspace.raw(SOURCE) / obj["relative_path"]
            if not ledger.is_complete("overture.download", obj["key"], inputs_hash):
                part = destination.with_name(destination.name + ".part")
                remaining = obj["size"] - (part.stat().st_size if part.exists() else 0)
                _budget(workspace, max(0, remaining))
                print(f"Downloading {obj['key']} ({obj['size']} bytes)", flush=True)
                download_file(
                    obj["url"],
                    destination,
                    expected_size=obj["size"],
                    etag=obj["etag"],
                    last_modified=obj["last_modified"],
                    retries=100,
                    timeout=60,
                )
                with pq.ParquetFile(destination) as parquet:
                    if not {"id", "geometry", "names", "subtype"}.issubset(
                        parquet.schema_arrow.names
                    ):
                        raise ValueError(f"Unexpected upstream schema: {destination}")
                    metadata = {
                        "rows": parquet.metadata.num_rows,
                        "row_groups": parquet.num_row_groups,
                        "schema_hash": hashlib.sha256(
                            parquet.schema_arrow.serialize().to_pybytes()
                        ).hexdigest(),
                    }
                ledger.complete(
                    "overture.download",
                    obj["key"],
                    inputs_hash,
                    [destination],
                    metadata=metadata,
                )
                print(f"Verified {destination.name}: {metadata}", flush=True)
            with pq.ParquetFile(destination) as parquet:
                counts[obj["type"]] = (
                    counts.get(obj["type"], 0) + parquet.metadata.num_rows
                )
        published = PUBLISHED_COUNTS.get(inventory["source_release"])
        if published is not None and published != counts:
            raise ValueError("Source footer counts disagree with release notes")
        write_json(
            workspace.raw(SOURCE) / "download-summary.json",
            {
                "source_release": inventory["source_release"],
                "publisher_counts": published,
                "publisher_counts_url": RELEASE_NOTES_URL if published else None,
                "rows": counts,
                "bytes": sum(obj["size"] for obj in inventory["objects"]),
                "elapsed_seconds": time.monotonic() - started,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
        print(
            f"DOWNLOAD COMPLETE: {counts}; {time.monotonic() - started:.1f}s",
            flush=True,
        )


def normalize(workspace: Workspace) -> None:
    """Normalize verified source objects into bounded, checkpointed partitions."""
    from .overture_normalize import run

    run(workspace)

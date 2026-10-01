"""Geoboundaries pins."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import Workspace, fingerprint
from .geoboundaries_config import MEDIA, REPO_API, SOURCE, _unit
from .geoboundaries_http import _metadata, _object, _read, _request
from .io import write_json


def _pin_path(workspace: Workspace, layer: dict[str, Any]) -> Path:
    path = workspace.raw(SOURCE) / "pins" / f"{_unit(layer)}.json"
    if path.exists() and _read(path)["metadata"] != layer:
        return path.with_name(f"{_unit(layer)}-{fingerprint(layer)[:16]}.json")
    return path


def _pin(workspace: Workspace, layer: dict[str, Any]) -> dict[str, Any]:
    raw = workspace.raw(SOURCE)
    path = _pin_path(workspace, layer)
    if path.exists():
        return _read(path)
    url = str(layer["staticDownloadLink"])
    match = re.fullmatch(
        r"https://github.com/wmgeolab/geoBoundaries/raw/([0-9a-f]{7,40})/(.+)", url
    )
    if match is None:
        raise ValueError(f"Unexpected non-pinned layer URL: {url}")
    short, suffix = match.groups()
    record = _metadata(f"{REPO_API}/commits/{short}", raw / "commits" / f"{short}.json")
    commit = str(_object(json.loads(record["body"]))["sha"])
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None or not commit.startswith(short):
        raise ValueError("Commit did not resolve to a matching full SHA")
    resolved = f"{MEDIA}/{commit}/{suffix}"
    with _request(resolved, method="HEAD") as response:
        size = int(response.getheader("Content-Length", "0"))
        etag = response.getheader("ETag")
        modified = response.getheader("Last-Modified")
    if size <= 0 or not etag or etag.startswith("W/"):
        raise ValueError("Layer needs a known size and a strong immutable ETag")
    end = min(31, size - 1)
    with _request(
        resolved, headers={"Range": f"bytes=0-{end}", "If-Range": etag}
    ) as response:
        if (
            response.status != 206
            or response.getheader("Content-Range") != f"bytes 0-{end}/{size}"
            or response.getheader("ETag") != etag
            or len(response.read(end + 2)) != end + 1
        ):
            raise ValueError("Layer route failed the pinned byte-range probe")
    result: dict[str, object] = {
        "url": resolved,
        "original_url": url,
        "commit": commit,
        "size": size,
        "etag": etag,
        "last_modified": modified,
        "range_verified": True,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "metadata": layer,
    }
    write_json(path, result)
    return result


def _archive_path(workspace: Workspace, pin: dict[str, Any]) -> Path:
    return (
        workspace.raw(SOURCE)
        / str(pin["commit"])
        / f"{_unit(_object(pin['metadata']))}.zip"
    )

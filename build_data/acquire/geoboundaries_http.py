"""Geoboundaries http."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.client import HTTPResponse
from pathlib import Path
from typing import Any, cast

from .geoboundaries_config import HEADERS, RETRY_ERRORS
from .io import write_json


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return cast(dict[str, Any], value)


def _read(path: Path) -> dict[str, Any]:
    return _object(json.loads(path.read_text(encoding="utf-8")))


def _request(
    url: str, *, method: str = "GET", headers: dict[str, str] | None = None
) -> HTTPResponse:
    request = urllib.request.Request(
        url, method=method, headers=HEADERS | (headers or {})
    )
    for attempt in range(6):
        try:
            return cast(HTTPResponse, urllib.request.urlopen(request, timeout=60))
        except RETRY_ERRORS:
            if attempt == 5:
                raise
            time.sleep(min(2**attempt, 30))
    raise AssertionError("Unreachable retry loop")


def _metadata(url: str, path: Path) -> dict[str, Any]:
    if path.exists():
        return _read(path)
    with _request(url) as response:
        data = response.read(8_000_001)
        if len(data) > 8_000_000:
            raise ValueError("Metadata response exceeds 8 MB")
        record: dict[str, object] = {
            "url": url,
            "resolved_url": response.url,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "etag": response.getheader("ETag"),
            "last_modified": response.getheader("Last-Modified"),
            "body": data.decode("utf-8"),
        }
    write_json(path, record)
    return record

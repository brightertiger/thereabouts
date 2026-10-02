"""Bounded HTTP discovery; actual transfers use the shared resumable downloader."""

import json
import re
import time
import urllib.request
from http.client import HTTPException, HTTPResponse
from typing import Any, cast

from .geonames_download import now


def get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=60) as response:
        return cast(dict[str, Any], json.load(response))


def probe(url: str) -> dict[str, Any]:
    """GET one byte also works with servers that reject HEAD (DB-IP)."""
    for attempt in range(10):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Range": "bytes=0-0",
                    "Accept-Encoding": "identity",
                    "User-Agent": "Thereabouts/acquire",
                },
            )
            with cast(HTTPResponse, urllib.request.urlopen(request, timeout=60)) as r:
                match = re.fullmatch(
                    r"bytes 0-0/(\d+)", r.getheader("Content-Range", "")
                )
                if r.status != 206 or match is None or len(r.read(2)) != 1:
                    raise ValueError(f"No verified byte range route: {url}")
                etag = r.getheader("ETag")
                if etag and etag.startswith("W/"):
                    etag = None
                modified = r.getheader("Last-Modified")
                if not (etag or modified):
                    raise ValueError(f"No stable validator: {url}")
                return dict(
                    size=int(match[1]),
                    etag=etag,
                    last_modified=modified,
                    retrieved_at=now(),
                    range_verified=True,
                )
        except (OSError, HTTPException):
            if attempt == 9:
                raise
            time.sleep(min(30, 2**attempt))
    raise AssertionError("unreachable")

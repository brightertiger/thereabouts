"""Bounded upstream inspection; candidate payloads are hashed without saving them."""

import hashlib
import json
import time
from dataclasses import dataclass
from http.client import HTTPResponse
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pipeline.config.sources import SourceSettings
from pipeline.pins.models import PinFile
from pipeline.runtime.paths import validate_relative


@dataclass
class Client:
    settings: SourceSettings
    payload_bytes: int = 0

    def open(
        self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None
    ) -> HTTPResponse:
        limits = self.settings.limits
        request = Request(
            url,
            method=method,
            headers={"Accept-Encoding": "identity", **(headers or {})},
        )
        for attempt in range(limits.retries + 1):
            try:
                return cast(
                    HTTPResponse, urlopen(request, timeout=limits.timeout_seconds)
                )
            except HTTPError as error:
                error.close()
                if error.code != 429 and error.code < 500:
                    raise
                if attempt == limits.retries:
                    raise
            except URLError:
                if attempt == limits.retries:
                    raise
            time.sleep(limits.backoff_seconds * (attempt + 1))
        raise AssertionError("Retry loop did not return or raise")

    def read(self, url: str) -> bytes:
        with self.open(url) as response:
            payload = response.read(self.settings.limits.row_bytes + 1)
        if len(payload) > self.settings.limits.row_bytes:
            raise ValueError(f"Upstream metadata exceeds row_bytes: {url}")
        return payload

    def json(self, url: str) -> Any:
        return json.loads(self.read(url))

    def pin(self, name: str, url: str, metadata: dict[str, Any]) -> PinFile:
        validate_relative(name)
        with self.open(url, method="HEAD") as response:
            size = int(response.headers.get("Content-Length", "-1"))
            etag = response.headers.get("ETag")
            modified = response.headers.get("Last-Modified")
        remaining = self.settings.limits.download_bytes - self.payload_bytes
        if size > remaining:
            raise ValueError(f"Proposal exceeds download_bytes before download: {name}")
        condition = {}
        if etag and not etag.startswith("W/"):
            condition["If-Match"] = etag
        elif modified:
            condition["If-Unmodified-Since"] = modified
        checksum = hashlib.sha256()
        observed = 0
        with self.open(url, headers=condition) as response:
            if etag and response.headers.get("ETag") != etag:
                raise ValueError(f"Upstream changed during proposal: {name}")
            while chunk := response.read(self.settings.limits.read_bytes):
                observed += len(chunk)
                if observed > remaining:
                    raise ValueError(
                        f"Proposal exceeds download_bytes while hashing: {name}"
                    )
                checksum.update(chunk)
        if size >= 0 and observed != size:
            raise ValueError(f"Upstream length changed during proposal: {name}")
        self.payload_bytes += observed
        result = PinFile(
            name, url, observed, checksum.hexdigest(), etag, modified, metadata
        )
        result.validate()
        return result

"""Append-only HTTP recovery with immutable validators and whole-file verification."""

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from http.client import HTTPException, HTTPResponse
from pathlib import Path
from typing import cast

from .io import publish, sha256_file, write_json


class RemoteChangedError(ValueError):
    """The requested snapshot is no longer available at this URL."""


class RangeResponseError(ValueError):
    """The server did not honor the exact requested byte range."""


class DownloadIntegrityError(ValueError):
    """A local or downloaded object does not match its pinned size/hash."""


class _RetryableError(OSError):
    pass


@dataclass
class _Pin:
    url: str
    size: int
    etag: str | None
    last_modified: str | None
    expected_sha256: str | None
    verified_sha256: str | None = None


def _open(request: urllib.request.Request, timeout: float) -> HTTPResponse:
    try:
        return cast(HTTPResponse, urllib.request.urlopen(request, timeout=timeout))
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 412:
            raise RemoteChangedError("The pinned remote validator changed") from error
        if error.code in (408, 429) or 500 <= error.code < 600:
            raise _RetryableError(f"Transient HTTP {error.code}") from error
        raise
    except (urllib.error.URLError, OSError, HTTPException) as error:
        raise _RetryableError(str(error)) from error


def _headers(response: HTTPResponse, pin: _Pin, offset: int) -> None:
    etag = response.getheader("ETag")
    modified = response.getheader("Last-Modified")
    if pin.etag is not None:
        if etag != pin.etag:
            raise RemoteChangedError(
                "ETag changed or disappeared; retain the old snapshot"
            )
    elif pin.last_modified is not None:
        if modified != pin.last_modified:
            raise RemoteChangedError("Last-Modified changed or disappeared")
    elif etag and not etag.startswith("W/"):
        pin.etag = etag
    elif modified:
        pin.last_modified = modified
    else:
        raise RangeResponseError(
            "A strong ETag or Last-Modified is required for resume"
        )

    if response.getheader("Content-Encoding", "identity") != "identity":
        raise RangeResponseError(
            "Encoded HTTP bodies cannot be appended by byte offset"
        )
    if offset and response.status != 206:
        raise RangeResponseError("Refusing HTTP 200/non-206 for a non-zero range")
    if response.status == 206:
        match = re.fullmatch(
            r"bytes (\d+)-(\d+)/(\d+)", response.getheader("Content-Range", "")
        )
        if match is None or tuple(map(int, match.groups())) != (
            offset,
            pin.size - 1,
            pin.size,
        ):
            raise RangeResponseError(
                "Content-Range does not match pinned size and offset"
            )
    elif response.status != 200:
        raise RangeResponseError(f"Unexpected HTTP {response.status}")
    length = response.getheader("Content-Length")
    if length is not None and (
        not length.isdigit() or int(length) != pin.size - offset
    ):
        raise RangeResponseError("Content-Length does not match pinned remaining size")


def _transfer(pin: _Pin, part: Path, receipt: Path, timeout: float) -> None:
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Accept-Encoding": "identity", "User-Agent": "PyOfflineGeocoder/acquire"}
    if pin.size:
        headers["Range"] = f"bytes={offset}-"
    validator = pin.etag or pin.last_modified
    if validator:
        headers["If-Range"] = validator
    if offset and validator is None:
        raise RangeResponseError("Cannot resume an unpinned partial object")
    with _open(urllib.request.Request(pin.url, headers=headers), timeout) as response:
        _headers(response, pin, offset)
        write_json(receipt, asdict(pin))
        with part.open("ab") as target:
            try:
                while True:
                    try:
                        block = response.read1(1024 * 1024)
                    except (OSError, HTTPException) as error:
                        raise _RetryableError(str(error)) from error
                    if not block:
                        break
                    if target.tell() + len(block) > pin.size:
                        raise DownloadIntegrityError("Body exceeds pinned size")
                    target.write(block)
            finally:
                target.flush()
                os.fsync(target.fileno())
    if part.stat().st_size < pin.size:
        raise _RetryableError("Connection ended before the pinned size was received")


def _verify(path: Path, size: int, checksum: str | None) -> str:
    if path.stat().st_size != size:
        raise DownloadIntegrityError(f"Size mismatch: {path}")
    actual = sha256_file(path)
    if checksum is not None and actual != checksum:
        raise DownloadIntegrityError(f"SHA256 mismatch: {path}")
    return actual


def download_file(
    url: str,
    destination: Path,
    *,
    expected_size: int,
    etag: str | None = None,
    last_modified: str | None = None,
    sha256: str | None = None,
    retries: int = 5,
    timeout: float = 60,
    backoff: float = 1,
) -> Path:
    """Resume pinned bytes, verify size/hash and publish; skip verified files."""
    if expected_size < 0 or retries < 0 or timeout <= 0 or backoff < 0:
        raise ValueError("Invalid size or retry settings")
    if etag is not None and (not etag or etag.startswith("W/")):
        raise ValueError(
            "If-Range requires a strong ETag; use Last-Modified for weak ETags"
        )
    if sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
        raise ValueError("sha256 must be a lowercase hex digest")
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    receipt = destination.with_name(destination.name + ".download.json")
    pin = _Pin(url, expected_size, etag, last_modified, sha256)
    if receipt.exists():
        saved = _Pin(**json.loads(receipt.read_text(encoding="utf-8")))
        if (
            saved.url != url
            or saved.size != expected_size
            or (etag is not None and etag != saved.etag)
            or (last_modified is not None and last_modified != saved.last_modified)
            or (sha256 is not None and saved.expected_sha256 not in (None, sha256))
        ):
            raise RemoteChangedError(
                "Download pins changed; choose a new snapshot path"
            )
        pin = saved
        if sha256 is not None:
            pin.expected_sha256 = sha256
    elif part.exists() and part.stat().st_size:
        raise DownloadIntegrityError(
            "Partial file has no pin receipt; cannot safely resume"
        )
    if destination.exists():
        checksum = pin.expected_sha256 or pin.verified_sha256
        if checksum is None:
            raise DownloadIntegrityError(
                "Existing file has no checksum or verification receipt"
            )
        _verify(destination, pin.size, checksum)
        return destination
    for attempt in range(retries + 1):
        if part.exists() and part.stat().st_size > pin.size:
            raise DownloadIntegrityError("Partial file exceeds pinned size")
        if part.exists() and part.stat().st_size == pin.size:
            break
        try:
            _transfer(pin, part, receipt, timeout)
            break
        except _RetryableError:
            if attempt == retries:
                raise
            delay = min(60.0, backoff * 2 ** min(attempt, 16))
            time.sleep(random.uniform(delay / 2, delay))
    pin.verified_sha256 = _verify(
        part, pin.size, pin.expected_sha256 or pin.verified_sha256
    )
    # Receipt first: a crash before rename leaves a verifiable full .part to adopt.
    write_json(receipt, asdict(pin))
    publish(part, destination)
    return destination

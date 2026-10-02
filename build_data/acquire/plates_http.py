"""Cached, polite acquisition of small web documents and query responses.

Wikimedia APIs do not promise byte ranges. These documents resume at file
boundaries; failed partial bodies are retained and never appended to a new reply.
The range-capable route uses the shared downloader for pinned large objects.
"""

import fcntl
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from typing import Any

from .artifacts import read_json
from .geonames_download import now
from .io import publish, sha256_file, write_json

CLIENT = (
    "PyOfflineGeocoder-plates/1.0 (+https://github.com/brightertiger/PyOfflineGeocoder)"
)
MAX_DOCUMENT_BYTES = 64_000_000


def fetch(
    root: Path, name: str, url: str, *, interval: float = 1.1, retries: int = 2
) -> dict[str, Any]:
    """Cache response bytes and a hash receipt; retain every failed HTTP body."""
    target = root / name
    receipt = target.with_name(target.name + ".http.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    if receipt.exists():
        saved = read_json(receipt)
        if saved["request_url"] != url:
            raise ValueError(f"Changed URL for cached document: {name}")
        if target.exists():
            if sha256_file(target) != saved["sha256"]:
                raise ValueError(f"Corrupt cached document: {name}")
            return saved
    host = urllib.parse.urlsplit(url).netloc
    lock = root.parent / f".{host}.http-lock"
    for attempt in range(retries + 1):
        with lock.open("a+") as guard:
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
            guard.seek(0)
            previous = guard.read()
            delay = max(0.0, float(previous or 0) + max(1.0, interval) - time.time())
            time.sleep(delay)
            guard.seek(0)
            guard.truncate()
            guard.write(str(time.time()))
            guard.flush()
            stamp = now()
            part = target.with_name(target.name + f".{time.time_ns()}.part")
            request = urllib.request.Request(
                url, headers={"User-Agent": CLIENT, "Accept-Encoding": "identity"}
            )
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    headers = dict(response.headers.items())
                    with part.open("wb") as stream:
                        while block := response.read(1024 * 1024):
                            stream.write(block)
                            if stream.tell() > MAX_DOCUMENT_BYTES:
                                raise ValueError("Web document exceeds 64 MB bound")
                        stream.flush()
                        os.fsync(stream.fileno())
                    length = response.headers.get("Content-Length")
                    if length and part.stat().st_size != int(length):
                        raise OSError("Incomplete HTTP response body")
                    saved = dict(
                        request_url=url,
                        response_url=response.url,
                        retrieved_at=stamp,
                        status=response.status,
                        headers=headers,
                        size=part.stat().st_size,
                        sha256=sha256_file(part),
                    )
                publish(part, target)
                write_json(receipt, saved)
                return saved
            except urllib.error.HTTPError as error:
                body = error.read(MAX_DOCUMENT_BYTES)
                part.write_bytes(body)
                write_json(
                    part.with_suffix(".error.json"),
                    dict(url=url, status=error.code, retrieved_at=stamp),
                )
                code = error.code
                retry_after = error.headers.get("Retry-After", "")
                error.close()
                if code not in (408, 429, 500, 502, 503, 504) or attempt == retries:
                    raise
                wait = 65.0
                if retry_after.isdigit():
                    wait = float(retry_after)
                elif retry_after:
                    with suppress(TypeError, ValueError, OverflowError):
                        wait = max(
                            0,
                            parsedate_to_datetime(retry_after).timestamp()
                            - time.time(),
                        )
                guard.seek(0)
                guard.truncate()
                guard.write(str(time.time() + wait))
                guard.flush()
            except (OSError, HTTPException):
                if attempt == retries:
                    raise
        time.sleep(min(30, 2 ** (attempt + 1)))
    raise AssertionError("unreachable")


def wiki_url(title: str, language: str = "en", revision: int | None = None) -> str:
    params: dict[str, str | int] = {
        "action": "parse",
        "prop": "text|revid|sections",
        "format": "json",
    }
    if revision is None:
        params.update(page=title, redirects=1)
    else:
        params["oldid"] = revision
    return f"https://{language}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        params
    )


def wiki_document(path: Path) -> tuple[str, int]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if "error" in value:
        raise ValueError(f"Wikipedia: {value['error']}")
    parsed = value["parse"]
    return str(parsed["text"]["*"]), int(parsed["revid"])

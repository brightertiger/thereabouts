"""Stream an object into a resumable part file, hashing every byte it keeps."""

import hashlib
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pipeline.config.sources import SourceLimits
from pipeline.runtime.jsonio import sync_directory

from .objects import backend
from .retry import Interrupted, Patience, retrying

USER_AGENT = "Thereabouts-pipeline (+https://github.com/brightertiger/thereabouts)"


class Restart(Interrupted):
    """The kept prefix cannot be continued; the next attempt starts at byte 0."""


@dataclass(frozen=True)
class Response:
    stream: BinaryIO
    start: int
    length: int | None
    etag: str | None


@dataclass(frozen=True)
class Received:
    size: int
    sha256: str
    md5: str
    resumed: bool


def _start(content_range: str | None, size: int) -> int:
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", content_range or "")
    if not match or (size >= 0 and match[3] not in ("*", str(size))):
        raise ValueError(f"Unexpected Content-Range: {content_range}")
    return int(match[1])


@contextmanager
def opened(
    url: str, offset: int, *, size: int, headers: dict[str, str], timeout: float
) -> Iterator[Response]:
    """Open at `offset`; a publisher may answer from byte 0 instead."""
    if not url.startswith(("http://", "https://")):
        fs, name = backend(url)
        with fs.open(name, "rb") as stream:
            stream.seek(offset)
            yield Response(stream, offset, None, None)
        return
    request = Request(
        url,
        headers={
            "Accept-Encoding": "identity",
            "User-Agent": USER_AGENT,
            **headers,
            **({"Range": f"bytes={offset}-"} if offset else {}),
        },
    )
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as error:
        error.close()
        if error.code == 416 and offset:
            raise Restart(f"Publisher refused to resume at byte {offset}") from error
        raise
    with response:
        start = 0
        if response.status == 206:
            start = _start(response.headers.get("Content-Range"), size)
            if start != offset:
                raise ValueError(f"Publisher resumed at byte {start}, not {offset}")
        length = response.headers.get("Content-Length")
        yield Response(
            cast(BinaryIO, response),
            start,
            int(length) if length is not None else None,
            response.headers.get("ETag"),
        )


def receive(
    part: Path,
    url: str,
    *,
    size: int,
    limit: int,
    headers: dict[str, str],
    timeout: float,
    chunk_bytes: int,
    etag: str | None = None,
) -> Received:
    """Continue `part` from its length; `size` is -1 when the publisher omits it.

    A body that ends early keeps its bytes for the next attempt. A response that
    cannot be the expected object discards them.
    """
    part.parent.mkdir(parents=True, exist_ok=True)
    offset = part.stat().st_size if part.exists() else 0
    if offset > limit or (size >= 0 and offset > size):
        part.unlink()
        offset = 0
    sha256, md5 = hashlib.sha256(), hashlib.md5()
    try:
        if offset and offset == size:
            # A complete part from an interrupted run needs no request.
            with part.open("rb") as kept:
                while block := kept.read(chunk_bytes):
                    sha256.update(block)
                    md5.update(block)
            return Received(size, sha256.hexdigest(), md5.hexdigest(), True)
        with opened(url, offset, size=size, headers=headers, timeout=timeout) as reply:
            if etag is not None and reply.etag != etag:
                raise ValueError(f"Upstream changed during transfer: {url}")
            expected = size - reply.start if size >= 0 else None
            if reply.length is not None and expected not in (None, reply.length):
                raise ValueError(f"Upstream length differs from the pinned size: {url}")
            if reply.length is not None and reply.start + reply.length > limit:
                raise ValueError(f"Object exceeds its byte limit: {url}")
            with part.open("r+b" if reply.start else "wb") as output:
                while (remaining := reply.start - output.tell()) > 0:
                    block = output.read(min(chunk_bytes, remaining))
                    if not block:
                        raise Restart(f"Kept prefix shrank during transfer: {part}")
                    sha256.update(block)
                    md5.update(block)
                copied = reply.start
                while block := reply.stream.read(chunk_bytes):
                    copied += len(block)
                    if copied > limit:
                        raise ValueError(f"Object exceeds its byte limit: {url}")
                    sha256.update(block)
                    md5.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            end = size if size >= 0 else None
            if end is None and reply.length is not None:
                end = reply.start + reply.length
            if end is not None and copied < end:
                raise Interrupted(f"Body ended at byte {copied} of {end}: {url}")
    except (Restart, ValueError):
        part.unlink(missing_ok=True)
        raise
    return Received(copied, sha256.hexdigest(), md5.hexdigest(), reply.start > 0)


def publish(part: Path, target: Path) -> None:
    os.replace(part, target)
    sync_directory(target.parent)


def fetch(
    url: str,
    target: Path,
    *,
    size: int,
    sha256: str,
    headers: dict[str, str],
    limits: SourceLimits,
    md5: str | None = None,
) -> None:
    """Retry and resume until `target` holds exactly the pinned bytes."""
    part = target.with_name(target.name + ".part")

    def attempt() -> None:
        received = receive(
            part,
            url,
            size=size,
            limit=size,
            headers=headers,
            timeout=limits.timeout_seconds,
            chunk_bytes=limits.read_bytes,
        )
        if received.sha256 != sha256 or md5 not in (None, received.md5):
            part.unlink()
            if received.resumed:
                raise Restart(f"Resumed object failed verification: {url}")
            raise ValueError("Object does not match its pinned size and SHA256")
        publish(part, target)

    retrying(
        Patience.of(limits),
        attempt,
        lambda: part.stat().st_size if part.exists() else 0,
    )

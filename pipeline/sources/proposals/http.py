"""Bounded upstream inspection; each payload streams once into the raw store."""

import hashlib
import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.client import HTTPResponse
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pipeline.config.sources import SourceSettings
from pipeline.pins.evidence import verify_publisher
from pipeline.pins.models import PinFile
from pipeline.runtime.jsonio import digest, write_json
from pipeline.runtime.paths import located, validate_relative
from pipeline.storage.objects import address, mirror
from pipeline.storage.retry import Interrupted, Patience, retrying
from pipeline.storage.transfer import USER_AGENT, Received, publish, receive


@dataclass(frozen=True)
class Custody:
    """A workspace raw directory, and optionally its mirror, keeping payloads."""

    raw: Path
    mirror: str = ""


CUSTODY: ContextVar[Custody | None] = ContextVar("custody", default=None)


@contextmanager
def keeping(custody: Custody) -> Iterator[None]:
    token = CUSTODY.set(custody)
    try:
        yield
    finally:
        CUSTODY.reset(token)


@dataclass(frozen=True)
class Head:
    size: int
    etag: str | None
    last_modified: str | None

    def conditions(self) -> dict[str, str]:
        if self.etag and not self.etag.startswith("W/"):
            return {"If-Match": self.etag}
        if self.last_modified:
            return {"If-Unmodified-Since": self.last_modified}
        return {}


@dataclass
class Client:
    settings: SourceSettings
    payload_bytes: int = 0
    custody: Custody | None = field(default_factory=CUSTODY.get)

    def now(self) -> datetime:
        """The proposal time, which selects time-named releases such as months."""
        return datetime.now(UTC)

    @property
    def patience(self) -> Patience:
        return Patience.of(self.settings.limits)

    def request(
        self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None
    ) -> HTTPResponse:
        """One attempt; callers retry the whole exchange, body included."""
        request = Request(
            url,
            method=method,
            headers={
                "Accept-Encoding": "identity",
                "User-Agent": USER_AGENT,
                **(headers or {}),
            },
        )
        try:
            return cast(
                HTTPResponse,
                urlopen(request, timeout=self.settings.limits.timeout_seconds),
            )
        except HTTPError as error:
            error.close()
            raise

    def read(self, url: str) -> bytes:
        limit = self.settings.limits.row_bytes

        def attempt() -> bytes:
            with self.request(url) as response:
                payload = response.read(limit + 1)
                length = response.headers.get("Content-Length")
            if len(payload) > limit:
                raise ValueError(f"Upstream metadata exceeds row_bytes: {url}")
            if length is not None and len(payload) != int(length):
                raise Interrupted(f"Upstream metadata ended early: {url}")
            return payload

        return retrying(self.patience, attempt)

    def json(self, url: str) -> Any:
        return json.loads(self.read(url))

    def document(self, url: str) -> tuple[bytes, str]:
        """A small upstream document and the SHA256 that evidences it."""
        body = self.read(url)
        return body, hashlib.sha256(body).hexdigest()

    def head(self, url: str) -> Head:
        def attempt() -> Head:
            with self.request(url, method="HEAD") as response:
                return Head(
                    int(response.headers.get("Content-Length", "-1")),
                    response.headers.get("ETag"),
                    response.headers.get("Last-Modified"),
                )

        return retrying(self.patience, attempt)

    @contextmanager
    def objects(self) -> Iterator[Path]:
        """The source's object directory; without custody, a discarded one."""
        if self.custody is not None:
            yield located(self.custody.raw, f"{self.settings.name}/sha256")
            return
        with tempfile.TemporaryDirectory(prefix="thereabouts-proposal-") as name:
            yield Path(name)

    def progress(self) -> Path | None:
        if self.custody is None:
            return None
        return located(self.custody.raw, f"{self.settings.name}/proposal-progress.json")

    def kept(self, objects: Path, url: str, head: Head) -> Received | None:
        """A payload stored by an interrupted proposal, if upstream still matches."""
        path = self.progress()
        if path is None or not path.is_file():
            return None
        entry = json.loads(path.read_bytes()).get(url)
        strong = bool(head.etag and not head.etag.startswith("W/"))
        if not entry or not (strong or head.last_modified):
            return None
        if [entry["size"], entry["etag"], entry["last_modified"]] != [
            head.size,
            head.etag,
            head.last_modified,
        ]:
            return None
        stored = objects / entry["sha256"]
        if not stored.is_file() or stored.stat().st_size != entry["size"]:
            return None
        sha256, md5 = hashlib.sha256(), hashlib.md5()
        with stored.open("rb") as stream:
            while block := stream.read(self.settings.limits.read_bytes):
                sha256.update(block)
                md5.update(block)
        if sha256.hexdigest() != entry["sha256"]:
            return None
        self.mirror(stored, entry["size"], entry["sha256"])
        return Received(entry["size"], entry["sha256"], md5.hexdigest(), False)

    def mirror(self, path: Path, size: int, sha256: str) -> None:
        if self.custody is None or not self.custody.mirror:
            return
        url = self.custody.mirror.rstrip("/") + "/" + address(sha256)
        limits = self.settings.limits
        retrying(
            self.patience, lambda: mirror(path, url, size, sha256, limits.read_bytes)
        )

    def store(self, objects: Path, url: str, head: Head, limit: int) -> Received:
        """Stream a payload once, hashing it into the object store and mirror."""
        limits = self.settings.limits
        # The part is bound to the validators it was fetched under.
        part = objects / (
            digest([url, head.size, head.etag, head.last_modified]) + ".part"
        )

        def attempt() -> Received:
            received = receive(
                part,
                url,
                size=head.size,
                limit=limit,
                headers=head.conditions(),
                timeout=limits.timeout_seconds,
                chunk_bytes=limits.read_bytes,
                etag=head.etag,
            )
            publish(part, objects / received.sha256)
            return received

        received = retrying(
            self.patience, attempt, lambda: part.stat().st_size if part.exists() else 0
        )
        if (path := self.progress()) is not None:
            entries = json.loads(path.read_bytes()) if path.is_file() else {}
            entries[url] = {
                "size": received.size,
                "etag": head.etag,
                "last_modified": head.last_modified,
                "sha256": received.sha256,
            }
            write_json(path, entries)
        self.mirror(objects / received.sha256, received.size, received.sha256)
        return received

    def pin(self, name: str, url: str, metadata: dict[str, Any]) -> PinFile:
        validate_relative(name)
        head = self.head(url)
        remaining = self.settings.limits.download_bytes - self.payload_bytes
        if head.size > remaining:
            raise ValueError(f"Proposal exceeds download_bytes before download: {name}")
        with self.objects() as objects:
            received = self.kept(objects, url, head) or self.store(
                objects, url, head, remaining
            )
            if head.size >= 0 and received.size != head.size:
                raise ValueError(f"Upstream length changed during proposal: {name}")
            verify_publisher(
                objects / received.sha256,
                metadata,
                self.settings.limits.read_bytes,
                name,
            )
        self.payload_bytes += received.size
        result = PinFile(
            name,
            url,
            received.size,
            received.sha256,
            head.etag,
            head.last_modified,
            metadata,
        )
        result.validate()
        return result

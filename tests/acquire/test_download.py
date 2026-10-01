"""Real HTTP tests for interruption, validators and byte-range corruption."""

import hashlib
import importlib
import json
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from build_data.acquire.download import (
    DownloadIntegrityError,
    RangeResponseError,
    RemoteChangedError,
    download_file,
)

download_module = importlib.import_module("build_data.acquire.download")


@dataclass
class Server:
    data: bytes = bytes(range(251)) * 9000
    etag: str | None = '"version-1"'
    modified: str = "Thu, 01 Oct 2026 01:00:00 GMT"
    drops: int = 0
    ignore_ranges: bool = False
    change_etag: bool = False
    bad_range: bool = False
    bad_length: bool = False
    statuses: list[int] = field(default_factory=list)
    requests: list[tuple[str | None, str | None]] = field(default_factory=list)
    url: str = ""


@pytest.fixture
def server() -> Iterator[Server]:
    state = Server()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            requested = self.headers.get("Range")
            validator = self.headers.get("If-Range")
            state.requests.append((requested, validator))
            if state.statuses:
                self.send_response(state.statuses.pop(0))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            offset = (
                int(requested.removeprefix("bytes=").removesuffix("-"))
                if requested
                else 0
            )
            current = (
                state.etag
                if state.etag and not state.etag.startswith("W/")
                else state.modified
            )
            ranged = (
                requested is not None
                and not state.ignore_ranges
                and validator in (None, current)
            )
            if not ranged:
                offset = 0
            self.send_response(206 if ranged else 200)
            if state.etag:
                self.send_header("ETag", state.etag)
            self.send_header("Last-Modified", state.modified)
            self.send_header(
                "Content-Length", str(len(state.data) - offset + int(state.bad_length))
            )
            if ranged:
                self.send_header(
                    "Content-Range",
                    f"bytes {offset + int(state.bad_range)}-"
                    f"{len(state.data) - 1}/{len(state.data)}",
                )
            self.end_headers()
            dropping = state.drops > 0
            body = (
                state.data[offset : offset + 65536] if dropping else state.data[offset:]
            )
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            if dropping:
                state.drops -= 1
                if state.change_etag:
                    state.etag = '"version-2"'
                self.connection.shutdown(socket.SHUT_RDWR)
                self.close_connection = True

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{http.server_port}/object"
    worker = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01})
    worker.start()
    try:
        yield state
    finally:
        http.shutdown()
        worker.join()
        http.server_close()


def test_multiple_disconnects_resume_and_second_run_is_offline(
    server: Server, tmp_path: Path
) -> None:
    destination = tmp_path / "object"
    server.drops = 2
    checksum = hashlib.sha256(server.data).hexdigest()
    download_file(
        server.url,
        destination,
        expected_size=len(server.data),
        sha256=checksum,
        backoff=0,
    )
    assert destination.read_bytes() == server.data
    assert server.requests == [
        ("bytes=0-", None),
        ("bytes=65536-", '"version-1"'),
        ("bytes=131072-", '"version-1"'),
    ]
    assert not (tmp_path / "object.part").exists()
    download_file(
        server.url, destination, expected_size=len(server.data), sha256=checksum
    )
    assert len(server.requests) == 3


def test_resume_across_invocations(server: Server, tmp_path: Path) -> None:
    destination = tmp_path / "object"
    server.drops = 1
    with pytest.raises(OSError, match="Connection ended"):
        download_file(
            server.url, destination, expected_size=len(server.data), retries=0
        )
    assert not destination.exists()
    assert (tmp_path / "object.part").read_bytes() == server.data[:65536]
    download_file(server.url, destination, expected_size=len(server.data))
    assert destination.read_bytes() == server.data
    assert server.requests[-1] == ("bytes=65536-", '"version-1"')


@pytest.mark.parametrize("changed", [False, True])
def test_never_append_200_or_changed_etag(
    server: Server, tmp_path: Path, changed: bool
) -> None:
    server.drops = 1
    destination = tmp_path / "object"
    with pytest.raises(OSError):
        download_file(
            server.url, destination, expected_size=len(server.data), retries=0
        )
    if changed:
        server.etag = '"version-2"'
    else:
        server.ignore_ranges = True
    with pytest.raises(RemoteChangedError if changed else RangeResponseError):
        download_file(server.url, destination, expected_size=len(server.data))
    assert not destination.exists()
    assert (tmp_path / "object.part").read_bytes() == server.data[:65536]
    assert len(server.requests) == 2


def test_change_during_retry_preserves_partial(server: Server, tmp_path: Path) -> None:
    server.drops = 1
    server.change_etag = True
    with pytest.raises(RemoteChangedError):
        download_file(
            server.url, tmp_path / "object", expected_size=len(server.data), backoff=0
        )
    assert (tmp_path / "object.part").read_bytes() == server.data[:65536]


@pytest.mark.parametrize("weak", [False, True])
def test_last_modified_fallback(server: Server, tmp_path: Path, weak: bool) -> None:
    server.etag = 'W/"weak"' if weak else None
    server.drops = 1
    download_file(
        server.url, tmp_path / "object", expected_size=len(server.data), backoff=0
    )
    assert server.requests[1][1] == server.modified


@pytest.mark.parametrize("bad_header", ["range", "length"])
def test_bad_range_and_length_never_publish(
    server: Server, tmp_path: Path, bad_header: str
) -> None:
    server.bad_range = bad_header == "range"
    server.bad_length = bad_header == "length"
    with pytest.raises(RangeResponseError):
        download_file(server.url, tmp_path / "object", expected_size=len(server.data))
    assert not (tmp_path / "object").exists()
    assert not (tmp_path / "object.part").exists()


def test_hash_failure_and_corrupt_existing_file(server: Server, tmp_path: Path) -> None:
    destination = tmp_path / "object"
    with pytest.raises(DownloadIntegrityError, match="SHA256"):
        download_file(
            server.url, destination, expected_size=len(server.data), sha256="0" * 64
        )
    assert not destination.exists()
    good = tmp_path / "good"
    download_file(server.url, good, expected_size=len(server.data))
    good.write_bytes(b"x" * len(server.data))
    with pytest.raises(DownloadIntegrityError, match="SHA256"):
        download_file(server.url, good, expected_size=len(server.data))
    assert len(server.requests) == 2


def test_transient_http_retries_use_exponential_jitter(
    server: Server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server.statuses = [503, 429]
    sleeps: list[float] = []
    monkeypatch.setattr(download_module.time, "sleep", sleeps.append)
    download_file(
        server.url, tmp_path / "object", expected_size=len(server.data), backoff=2
    )
    assert 1 <= sleeps[0] <= 2
    assert 2 <= sleeps[1] <= 4
    assert len(server.requests) == 3


def test_network_failure_is_retried_and_exhaustion_is_bounded(
    server: Server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.error

    calls = 0

    def offline(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(download_module.urllib.request, "urlopen", offline)
    with pytest.raises(OSError, match="offline"):
        download_file(
            server.url,
            tmp_path / "object",
            expected_size=len(server.data),
            retries=2,
            backoff=0,
        )
    assert calls == 3
    assert not (tmp_path / "object").exists()


def test_full_partial_adopted_after_crash_before_rename(
    server: Server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "object"
    original = download_module.publish

    def crash(temporary: Path, final: Path) -> None:
        raise InterruptedError("simulated process interruption")

    monkeypatch.setattr(download_module, "publish", crash)
    with pytest.raises(InterruptedError):
        download_file(server.url, destination, expected_size=len(server.data))
    receipt = json.loads((tmp_path / "object.download.json").read_text())
    assert receipt["verified_sha256"] == hashlib.sha256(server.data).hexdigest()
    monkeypatch.setattr(download_module, "publish", original)
    download_file(server.url, destination, expected_size=len(server.data))
    assert destination.read_bytes() == server.data
    assert len(server.requests) == 1


def test_changed_local_pins_and_unpinned_partial_rejected(
    server: Server, tmp_path: Path
) -> None:
    destination = tmp_path / "object"
    download_file(server.url, destination, expected_size=len(server.data))
    with pytest.raises(RemoteChangedError):
        download_file(
            server.url, destination, expected_size=len(server.data), etag='"new"'
        )
    (tmp_path / "orphan.part").write_bytes(b"orphan")
    with pytest.raises(DownloadIntegrityError, match="no pin receipt"):
        download_file(server.url, tmp_path / "orphan", expected_size=len(server.data))
    assert len(server.requests) == 1


def test_empty_download(server: Server, tmp_path: Path) -> None:
    server.data = b""
    destination = download_file(server.url, tmp_path / "empty", expected_size=0)
    assert destination.read_bytes() == b""

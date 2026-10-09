"""Resumable transfers keep verified prefixes and recover from flaky publishers."""

import hashlib
from pathlib import Path
from urllib.error import HTTPError

import fsspec
import pytest

from pipeline.config.sources import SourceLimits
from pipeline.storage.transfer import USER_AGENT, fetch, receive

from .flaky_server import Step, flaky

BODY = bytes(range(256)) * 400
HALF = len(BODY) // 2
SHA = hashlib.sha256(BODY).hexdigest()
LIMITS = SourceLimits(
    retries=3, backoff_seconds=0.0, timeout_seconds=5.0, read_bytes=4096
)


def download(url: str, target: Path, size: int = len(BODY)) -> None:
    fetch(url, target, size=size, sha256=SHA, headers={}, limits=LIMITS)


def test_cleanly_closed_body_resumes_with_a_range_request(tmp_path: Path) -> None:
    with flaky(BODY, [Step(cut=HALF)]) as server:
        download(server.url, tmp_path / "object")
    assert (tmp_path / "object").read_bytes() == BODY
    assert server.ranges() == [None, f"bytes={HALF}-"]
    assert server.requests[0][1]["User-Agent"] == USER_AGENT
    assert not list(tmp_path.glob("*.part"))


def test_reset_connection_resumes_from_the_bytes_it_kept(tmp_path: Path) -> None:
    with flaky(BODY, [Step(cut=HALF, reset=True)]) as server:
        download(server.url, tmp_path / "object")
    assert (tmp_path / "object").read_bytes() == BODY
    first, second = server.ranges()
    # A reset may discard bytes in flight; the resume starts after those kept.
    kept = int((second or "bytes=0-").removeprefix("bytes=").rstrip("-"))
    assert first is None and 0 <= kept <= HALF


def test_publisher_without_ranges_restarts_from_the_first_byte(tmp_path: Path) -> None:
    with flaky(BODY, [Step(cut=HALF), Step(ranges=False)]) as server:
        download(server.url, tmp_path / "object")
    assert (tmp_path / "object").read_bytes() == BODY
    assert server.gets() == 2


def test_refused_range_discards_the_prefix_and_restarts(tmp_path: Path) -> None:
    with flaky(BODY, [Step(cut=HALF), Step(status=416)]) as server:
        download(server.url, tmp_path / "object")
    assert (tmp_path / "object").read_bytes() == BODY
    assert server.ranges() == [None, f"bytes={HALF}-", None]


def test_resumed_bytes_that_fail_verification_restart_once(tmp_path: Path) -> None:
    other = bytes(reversed(BODY))
    with flaky(BODY, [Step(cut=HALF, body=other)]) as server:
        download(server.url, tmp_path / "object")
    assert (tmp_path / "object").read_bytes() == BODY
    assert server.ranges() == [None, f"bytes={HALF}-", None]


def test_server_errors_are_retried(tmp_path: Path) -> None:
    with flaky(BODY, [Step(status=503), Step(status=429)]) as server:
        download(server.url, tmp_path / "object")
    assert server.gets() == 3


@pytest.mark.parametrize("code", [404, 412])
def test_deterministic_statuses_are_not_retried(tmp_path: Path, code: int) -> None:
    with (
        flaky(BODY, [Step(status=code)]) as server,
        pytest.raises(HTTPError) as error,
    ):
        download(server.url, tmp_path / "object")
    assert error.value.code == code
    assert server.gets() == 1
    assert not (tmp_path / "object").exists()


def test_length_disagreeing_with_the_pin_fails_without_retry(tmp_path: Path) -> None:
    with flaky(BODY, []) as server, pytest.raises(ValueError, match="pinned size"):
        download(server.url, tmp_path / "object", size=len(BODY) + 1)
    assert server.gets() == 1
    assert not list(tmp_path.iterdir())


def test_exhausted_retries_keep_the_prefix_for_the_next_run(tmp_path: Path) -> None:
    limits = SourceLimits(retries=0, backoff_seconds=0.0, timeout_seconds=5.0)
    target = tmp_path / "object"
    with flaky(BODY, [Step(cut=HALF)]) as server:
        with pytest.raises(ConnectionError, match="ended"):
            fetch(
                server.url,
                target,
                size=len(BODY),
                sha256=SHA,
                headers={},
                limits=limits,
            )
        assert target.with_name("object.part").stat().st_size == HALF
        fetch(server.url, target, size=len(BODY), sha256=SHA, headers={}, limits=limits)
    assert target.read_bytes() == BODY
    assert server.ranges() == [None, f"bytes={HALF}-"]


def test_filesystem_sources_resume_by_seeking(tmp_path: Path) -> None:
    fs = fsspec.filesystem("memory")
    with fs.open("/transfer/object", "wb") as stream:
        stream.write(BODY)
    part = tmp_path / "object.part"
    part.write_bytes(BODY[:HALF])
    received = receive(
        part,
        "memory:///transfer/object",
        size=len(BODY),
        limit=len(BODY),
        headers={},
        timeout=5.0,
        chunk_bytes=4096,
    )
    assert received.resumed and received.size == len(BODY)
    assert received.sha256 == SHA
    assert received.md5 == hashlib.md5(BODY).hexdigest()
    assert part.read_bytes() == BODY


def test_oversized_body_is_rejected_and_discarded(tmp_path: Path) -> None:
    part = tmp_path / "object.part"
    with flaky(BODY, []) as server, pytest.raises(ValueError, match="exceeds"):
        receive(
            part,
            server.url,
            size=-1,
            limit=HALF,
            headers={},
            timeout=5.0,
            chunk_bytes=4096,
        )
    assert not part.exists()

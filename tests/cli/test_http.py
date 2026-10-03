"""Real console downloads are qualified against a loopback HTTP server only."""

import json
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from .helpers import console, release


@dataclass
class State:
    files: dict[str, bytes]
    interrupt: bool = False
    ignore_range: bool = False
    corrupt: bool = False
    ranges: list[str | None] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[str, State]]:
    directory = tmp_path / "release"
    release(directory)
    state = State({"/" + p.name: p.read_bytes() for p in directory.iterdir()})

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            state.requests.append(self.path)
            value = state.files.get(self.path)
            if value is None:
                self.send_error(404)
                return
            requested = self.headers.get("Range")
            if self.path.endswith(".tar"):
                state.ranges.append(requested)
                if state.corrupt:
                    value = value[:-1] + bytes([value[-1] ^ 1])
            offset = (
                int(requested.removeprefix("bytes=").removesuffix("-"))
                if requested
                else 0
            )
            total = len(value)
            if state.ignore_range:
                offset = 0
            self.send_response(206 if offset else 200)
            self.send_header("Content-Length", str(total - offset))
            if offset:
                self.send_header("Content-Range", f"bytes {offset}-{total - 1}/{total}")
            self.end_headers()
            if state.interrupt and self.path.endswith(".tar"):
                state.interrupt = False
                self.wfile.write(value[:1024])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            self.wfile.write(value[offset:])

    host = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=host.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{host.server_port}", state
    finally:
        host.shutdown()
        host.server_close()
        thread.join(timeout=5)


def test_interrupted_transfer_resumes_exact_range(
    tmp_path: Path, server: tuple[str, State]
) -> None:
    url, state = server
    store = tmp_path / "store"
    state.interrupt = True
    first = console(store, "data", "install", "phone", "--from", url, "--yes")
    assert first.returncode == 4
    assert not (store / "active.json").exists()
    partial = next((store / ".downloads").glob("*.part"))
    assert partial.stat().st_size == 1024
    state.ignore_range = True
    refused = console(store, "data", "install", "phone", "--from", url)
    assert refused.returncode == 4 and "resume range" in refused.stderr
    assert partial.stat().st_size == 1024
    state.ignore_range = False
    completed = console(store, "data", "install", "phone", "--from", url)
    assert completed.returncode == 0, completed.stderr
    assert state.ranges == [None, "bytes=1024-", "bytes=1024-"]
    assert not partial.exists()
    assert console(store, "data", "verify", "--full").returncode == 0
    assert console(store, "phone", "+32", "--country", "BE").returncode == 0


def test_checksum_failure_and_atomic_activation(
    tmp_path: Path, server: tuple[str, State]
) -> None:
    url, state = server
    store = tmp_path / "store"
    state.corrupt = True
    failed = console(store, "data", "install", "phone", "--from", url)
    assert failed.returncode == 4 and "checksum" in failed.stderr
    assert not (store / "active.json").exists()
    assert not list((store / ".downloads").glob("*.part"))
    state.corrupt = False
    assert console(store, "data", "install", "phone", "--from", url).returncode == 0
    before = (store / "active.json").read_bytes()
    index = json.loads(state.files["/index.json"])
    packs = index["datasets"]["2026.10"]["packs"]
    packs["postal"] = dict(packs["phone"])
    state.files["/index.json"] = json.dumps(index).encode()
    failed = console(store, "data", "install", "phone", "postal", "--from", url)
    assert failed.returncode == 4 and "identity" in failed.stderr
    assert (store / "active.json").read_bytes() == before


def test_remote_inventory_update_and_missing_artifact(
    tmp_path: Path, server: tuple[str, State]
) -> None:
    url, state = server
    store = tmp_path / "store"
    assert console(store, "data", "install", "phone", "--from", url).returncode == 0
    listed = console(store, "data", "list", "--remote", source=url)
    assert listed.returncode == 0
    assert json.loads(listed.stdout)["format"] == 2
    checked = console(store, "data", "update", "--check", source=url)
    assert checked.returncode == 0
    assert json.loads(checked.stdout)["update_available"] is False
    index = json.loads(state.files["/index.json"])
    index["datasets"]["2027.1"] = index["datasets"]["2026.10"]
    state.files["/index.json"] = json.dumps(index).encode()
    checked = console(store, "data", "update", "--check", source=url)
    assert json.loads(checked.stdout)["update_available"] is True
    del state.files["/phone.tar"]
    missing = console(tmp_path / "empty", "data", "install", "phone", "--from", url)
    assert missing.returncode == 4


@pytest.mark.skipif(__import__("os").name == "nt", reason="Unix lock interop test")
def test_concurrent_console_install_lock(tmp_path: Path) -> None:
    import fcntl

    source = tmp_path / "release"
    release(source)
    store = tmp_path / "store"
    store.mkdir()
    with (store / ".install.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        blocked = console(store, "data", "install", "phone", "--from", str(source))
        assert blocked.returncode == 4 and "install lock" in blocked.stderr
    assert not (store / "active.json").exists()
    installed = console(store, "data", "install", "phone", "--from", str(source))
    assert installed.returncode == 0


def test_lookup_never_fetches_a_configured_release(
    tmp_path: Path, server: tuple[str, State]
) -> None:
    url, state = server
    missing = console(
        tmp_path / "empty", "reverse", "--lat", "0", "--lon", "0", source=url
    )
    assert missing.returncode == 3
    assert missing.stderr == "thereabouts data install core\n"
    assert not state.requests

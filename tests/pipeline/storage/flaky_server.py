"""A loopback publisher whose responses fail in scripted, realistic ways."""

import socket
import struct
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Step:
    """One response: a status, or a body cut after `cut` bytes by FIN or RST."""

    status: int = 200
    cut: int | None = None
    reset: bool = False
    ranges: bool = True
    body: bytes | None = None


@dataclass
class Flaky:
    url: str
    body: bytes
    steps: list[Step]
    etag: str
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def ranges(self) -> list[str | None]:
        return [headers.get("Range") for method, headers in self.requests]

    def gets(self) -> int:
        return sum(method == "GET" for method, _ in self.requests)


@contextmanager
def flaky(body: bytes, steps: list[Step], etag: str = '"fixture"') -> Iterator[Flaky]:
    state = Flaky("", body, list(steps), etag)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_HEAD(self) -> None:
            self.respond(head=True)

        def do_GET(self) -> None:
            self.respond(head=False)

        def respond(self, *, head: bool) -> None:
            with lock:
                state.requests.append((self.command, dict(self.headers)))
                step = state.steps.pop(0) if state.steps and not head else Step()
            if step.status != 200:
                self.send_response(step.status)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            payload = state.body if step.body is None else step.body
            start = 0
            requested = self.headers.get("Range")
            if requested and step.ranges and not head:
                start = int(requested.removeprefix("bytes=").split("-")[0])
                if start >= len(payload):
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{len(payload)}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(206)
                end = len(payload) - 1
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
            else:
                self.send_response(200)
                self.send_header("Accept-Ranges", "bytes" if step.ranges else "none")
            self.send_header("Content-Length", str(len(payload) - start))
            self.send_header("ETag", state.etag)
            self.send_header("Last-Modified", "Thu, 01 Oct 2026 03:37:19 GMT")
            self.end_headers()
            if head:
                return
            if step.cut is None:
                self.wfile.write(payload[start:])
                return
            self.wfile.write(payload[start : start + step.cut])
            self.wfile.flush()
            if step.reset:
                self.connection.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
            self.close_connection = True
            self.connection.close()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    thread.start()
    try:
        state.url = f"http://127.0.0.1:{server.server_port}/payload.bin"
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

"""A loopback publisher with observable HEAD and conditional GET requests."""

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Reply:
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    status: int = 200
    get_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Publisher:
    url: str
    routes: dict[str, Reply]
    requests: list[tuple[str, str, dict[str, str]]]


@contextmanager
def publisher() -> Iterator[Publisher]:
    routes: dict[str, Reply] = {}
    requests: list[tuple[str, str, dict[str, str]]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self) -> None:
            self.respond()

        def do_GET(self) -> None:
            self.respond()

        def respond(self) -> None:
            requests.append((self.command, self.path, dict(self.headers)))
            reply = routes.get(self.path, Reply(b"missing", status=404))
            self.send_response(reply.status)
            headers = {
                "Content-Length": str(len(reply.body)),
                "ETag": '"' + hashlib.sha256(reply.body).hexdigest() + '"',
                "Last-Modified": "Thu, 01 Oct 2026 03:37:19 GMT",
                **reply.headers,
            }
            if self.command == "GET":
                headers.update(reply.get_headers)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(reply.body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    thread.start()
    try:
        yield Publisher(f"http://127.0.0.1:{server.server_port}", routes, requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

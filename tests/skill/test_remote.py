"""The URL form of the skill's dataset helper, when DuckDB's httpfs is installed."""

import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import duckdb
import pytest

from pipeline.runtime.fingerprints import REPOSITORY
from tests.skill import examples
from tests.skill.dataset import build

SKILL = REPOSITORY / "skills/thereabouts/SKILL.md"


class RangeHandler(SimpleHTTPRequestHandler):
    """Static files with byte ranges, which httpfs needs and http.server lacks."""

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        path = Path(self.translate_path(self.path))
        found = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if found is None or not path.is_file():
            return super().do_GET()
        data = path.read_bytes()
        size = len(data)
        if found.group(1):
            first = int(found.group(1))
            last = min(int(found.group(2) or size - 1), size - 1)
        else:
            first, last = max(size - int(found.group(2)), 0), size - 1
        body = data[first : last + 1]
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def httpfs_installed() -> bool:
    """Loading never downloads; a fresh machine skips instead of using the network."""
    try:
        duckdb.connect().load_extension("httpfs")
    except duckdb.Error:
        return False
    return True


@pytest.mark.skipif(
    not httpfs_installed(),
    reason="DuckDB httpfs is not installed and installing it needs the network",
)
def test_the_helper_reads_a_dataset_over_http(tmp_path: Path) -> None:
    root = build(tmp_path / "dataset")
    handler = partial(RangeHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        helper = next(e for e in examples.parse(SKILL) if e.language == "python")
        url = f"http://127.0.0.1:{server.server_address[1]}"
        namespace: dict[str, Any] = {"DATASET": url}
        exec(compile(helper.source, helper.where, "exec"), namespace)
        rows = (
            namespace["con"]
            .sql(
                "SELECT name FROM canonical_cities WHERE country_code = 'FR' "
                "ORDER BY population DESC"
            )
            .fetchall()
        )
    finally:
        server.shutdown()
        server.server_close()
    assert rows == [("Paris",), ("Tremblay-en-France",)]

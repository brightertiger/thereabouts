"""Transport caps and the default release URL have one Rust definition."""

import json

from tests.client.hosts import NODE_CLIENT, node
from thereabouts import _core


def test_python_exports_the_rust_transport_policy() -> None:
    assert _core.MAX_ARCHIVE_BYTES == 2 * 1024**3
    assert _core.MAX_UNPACKED_BYTES == 16 * 1024**3
    assert _core.INDEX_FORMAT == 3
    assert _core.ARCHIVE_SUFFIX == ".tar.zst"
    assert _core.DEFAULT_RELEASE_URL.startswith("https://")


def test_node_reads_the_same_values_as_python() -> None:
    script = f"""
const t = await import({json.dumps((NODE_CLIENT / "runtime/transport.js").as_uri())});
console.log(JSON.stringify([t.MAX_ARCHIVE_BYTES, t.MAX_UNPACKED_BYTES,
  t.INDEX_FORMAT, t.ARCHIVE_SUFFIX, t.DEFAULT_SOURCE]));
"""
    result = node(script)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        _core.MAX_ARCHIVE_BYTES,
        _core.MAX_UNPACKED_BYTES,
        _core.INDEX_FORMAT,
        _core.ARCHIVE_SUFFIX,
        _core.DEFAULT_RELEASE_URL,
    ]

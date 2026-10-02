import functools
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from thereabouts.installing.errors import DownloadError
from thereabouts.installing.install import install
from thereabouts.installing.transfer import validate_url
from thereabouts.packs.jsonio import sha256

from ..client.test_api import PACK


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    http = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(PACK))
    )
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}/manifest.json"
    finally:
        http.shutdown()
        thread.join()
        http.server_close()


def test_pinned_url_install_and_offline_refusal(tmp_path: Path, server: str) -> None:
    manifest = PACK / "manifest.json"
    options = {
        "manifest_sha256": sha256(manifest),
        "manifest_bytes": manifest.stat().st_size,
    }
    result = install(server, data_dir=tmp_path / "store", **options)  # type: ignore[arg-type]
    assert (result / "manifest.json").read_bytes() == manifest.read_bytes()
    with pytest.raises(DownloadError, match="Offline"):
        install(server, data_dir=tmp_path / "offline", offline=True, **options)  # type: ignore[arg-type]


@pytest.mark.parametrize("delta", [-1, 1])
def test_remote_manifest_count_is_bounded(
    tmp_path: Path, server: str, delta: int
) -> None:
    manifest = PACK / "manifest.json"
    with pytest.raises(DownloadError):
        install(
            server,
            data_dir=tmp_path,
            manifest_sha256=sha256(manifest),
            manifest_bytes=manifest.stat().st_size + delta,
        )
    assert not (tmp_path / "packs/reverse/current.json").exists()
    assert not list(tmp_path.rglob(".transfer-*"))


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/data",
        "ftp://example.org/data",
        "https://user:pass@example.org/data",
        "https://example.org/#fragment",
    ],
)
def test_unsafe_url(url: str) -> None:
    with pytest.raises(DownloadError):
        validate_url(url)


def test_url_requires_trusted_manifest_count(tmp_path: Path, server: str) -> None:
    from thereabouts.client_errors import InvalidInputError

    with pytest.raises(InvalidInputError, match="manifest_bytes"):
        install(
            server, data_dir=tmp_path, manifest_sha256=sha256(PACK / "manifest.json")
        )


def test_redirect_cannot_downgrade_https() -> None:
    from email.message import Message
    from urllib.request import Request

    from thereabouts.installing.transfer import SecureRedirects

    with pytest.raises(DownloadError, match="downgrade"):
        SecureRedirects().redirect_request(
            Request("https://example.invalid/manifest.json"),
            None,
            302,
            "Found",
            Message(),
            "http://127.0.0.1/manifest.json",
        )

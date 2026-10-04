"""Regression coverage for the suite-wide network prohibition."""

import socket
import urllib.request

import pytest


@pytest.mark.parametrize("host", ["example.com", "8.8.8.8", "::ffff:8.8.8.8"])
def test_external_dns_and_connections_fail_before_io(host: str) -> None:
    with pytest.raises(AssertionError, match="external hosts"):
        socket.getaddrinfo(host, 443)
    with pytest.raises(AssertionError, match="external hosts"):
        socket.create_connection((host, 443))
    with socket.socket() as sock:
        with pytest.raises(AssertionError, match="external networks"):
            sock.connect((host, 443))
        with pytest.raises(AssertionError, match="external networks"):
            sock.connect_ex((host, 443))
    with (
        socket.socket(type=socket.SOCK_DGRAM) as sock,
        pytest.raises(AssertionError, match="external networks"),
    ):
        sock.sendto(b"blocked", (host, 53))


def test_real_osm_url_is_blocked_before_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline.pins.lock import read_lock
    from pipeline.runtime.fingerprints import REPOSITORY

    SOURCE_URL = read_lock(REPOSITORY / "pins.lock")["osm_land"].files[0].url

    # Ignore host proxies so the failure demonstrates our DNS/socket guard.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with pytest.raises(AssertionError, match="external hosts"):
        opener.open(SOURCE_URL, timeout=1)


def test_loopback_proxy_cannot_tunnel_the_osm_download() -> None:
    from pipeline.pins.lock import read_lock
    from pipeline.runtime.fingerprints import REPOSITORY

    SOURCE_URL = read_lock(REPOSITORY / "pins.lock")["osm_land"].files[0].url

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": "http://127.0.0.1:1"})
    )
    with pytest.raises(AssertionError, match="external hosts"):
        opener.open(SOURCE_URL, timeout=1)

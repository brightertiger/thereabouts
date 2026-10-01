"""All tests may use loopback fixtures; DNS and outbound sockets fail immediately."""

import ipaddress
import socket
from http.client import HTTPConnection
from typing import Any
from urllib.parse import urlsplit

import pytest


def _local(host: object) -> bool:
    if host in (None, "localhost", b"localhost"):
        return True
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


def _check(address: object) -> None:
    # Local Unix sockets do not reach a network.
    if isinstance(address, str) and address.startswith("/"):
        return
    if not isinstance(address, tuple) or not _local(address[0]):
        raise AssertionError(f"Tests must not access external networks: {address!r}")


def install(monkeypatch: pytest.MonkeyPatch) -> None:
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    sendto = socket.socket.sendto
    getaddrinfo = socket.getaddrinfo
    set_tunnel = HTTPConnection.set_tunnel
    putrequest = HTTPConnection.putrequest

    def guarded_connect(sock: socket.socket, address: Any) -> None:
        _check(address)
        connect(sock, address)

    def guarded_connect_ex(sock: socket.socket, address: Any) -> int:
        _check(address)
        return connect_ex(sock, address)

    def guarded_sendto(sock: socket.socket, data: bytes, *args: Any) -> int:
        _check(args[-1])
        return sendto(sock, data, *args)

    def guarded_lookup(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _local(host):
            raise AssertionError(f"Tests must not resolve external hosts: {host!r}")
        return getaddrinfo(host, *args, **kwargs)

    def guarded_tunnel(
        connection: HTTPConnection, host: str, *args: Any, **kwargs: Any
    ) -> None:
        if not _local(host):
            raise AssertionError(f"Tests must not tunnel to external hosts: {host!r}")
        set_tunnel(connection, host, *args, **kwargs)

    def guarded_request(
        connection: HTTPConnection, method: str, url: str, *args: Any, **kwargs: Any
    ) -> None:
        host = urlsplit(url).hostname
        if host and not _local(host):
            raise AssertionError(f"Tests must not proxy external hosts: {host!r}")
        putrequest(connection, method, url, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", guarded_sendto)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_lookup)
    monkeypatch.setattr(HTTPConnection, "set_tunnel", guarded_tunnel)
    monkeypatch.setattr(HTTPConnection, "putrequest", guarded_request)
    if hasattr(socket.socket, "sendmsg"):
        sendmsg = socket.socket.sendmsg

        def guarded_sendmsg(sock: socket.socket, *args: Any) -> int:
            if len(args) >= 4:
                _check(args[3])
            return sendmsg(sock, *args)

        monkeypatch.setattr(socket.socket, "sendmsg", guarded_sendmsg)

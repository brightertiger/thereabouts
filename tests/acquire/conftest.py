"""Permit only loopback HTTP; external networking stays blocked."""

import socket

import pytest

_CONNECT = socket.socket.connect
_CREATE_CONNECTION = socket.create_connection


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def loopback(sock: socket.socket, address: tuple[str, int]) -> None:
        if not isinstance(address, tuple) or address[0] != "127.0.0.1":
            raise AssertionError("Only loopback HTTP is allowed")
        _CONNECT(sock, address)

    monkeypatch.setattr(socket.socket, "connect", loopback)
    monkeypatch.setattr(socket, "create_connection", _CREATE_CONNECTION)

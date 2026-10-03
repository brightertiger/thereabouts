"""Tests use committed synthetic inputs or loopback servers; never upstream data."""

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.network_guard import install

    install(monkeypatch)

"""Tests use committed synthetic inputs or loopback servers; never upstream data."""

import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.network_guard import install

    install(monkeypatch)


def pytest_configure(config: pytest.Config) -> None:
    """Create the parent of --basetemp; pytest makes only the last directory."""
    basetemp = config.getoption("basetemp", default=None)
    if basetemp:
        Path(basetemp).parent.mkdir(parents=True, exist_ok=True)

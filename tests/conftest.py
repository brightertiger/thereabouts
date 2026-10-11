"""Tests use committed synthetic inputs or loopback servers; never upstream data."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.network_guard import install

    install(monkeypatch)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Resolve --basetemp and create its parent before the tmp plugin reads it.

    pytest makes only the last directory of basetemp, and a relative basetemp
    (as in addopts) would make tmp_path relative to the current directory.
    """
    basetemp = config.getoption("basetemp", default=None)
    if basetemp:
        absolute = Path(basetemp).resolve()
        absolute.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(absolute)

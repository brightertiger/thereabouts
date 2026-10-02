"""The public table API, input validation, lifecycle and batch behavior."""

import dataclasses
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from thereabouts import ClosedGeocoderError, Geocoder, Location

from .conftest import FIXTURE


def test_location_is_small_frozen_slotted_value(geocoder: Geocoder) -> None:
    value = geocoder.reverse(52.37, 4.9)
    assert value == Location("Amsterdam", "Noord-Holland", "Netherlands", "NL")
    assert not hasattr(value, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, "city", "changed")  # noqa: B010


@pytest.mark.parametrize(
    "lat,lon",
    [
        (True, 0),
        (0, False),
        ("0", 0),
        (None, 0),
        (float("nan"), 0),
        (0, float("inf")),
        (-91, 0),
        (91, 0),
        (0, -181),
        (0, 181),
        (10**500, 0),
    ],
)
def test_invalid_coordinates(geocoder: Geocoder, lat: Any, lon: Any) -> None:
    with pytest.raises(ValueError):
        geocoder.reverse(lat, lon)
    with pytest.raises(ValueError):
        list(geocoder.reverse_many([(lat, lon)]))


def test_ocean_outside_region_and_batch(geocoder: Geocoder) -> None:
    points = [
        (52.37, 4.9),
        (50.85, 4.35),
        (53.5, 2.5),
        (0, 0),
        (90, 180),
        (-90, -180),
    ] * 800
    assert list(geocoder.reverse_many(points)) == [geocoder.reverse(*p) for p in points]
    assert geocoder.reverse(0, 0) is None
    assert geocoder.reverse(53.5, 2.5) is None
    assert list(geocoder.reverse_many([])) == []


def test_chunked_iteration_and_close(geocoder: Geocoder) -> None:
    consumed = 0

    def points() -> Iterator[tuple[float, float]]:
        nonlocal consumed
        for _ in range(10_000):
            consumed += 1
            yield 52.37, 4.9

    results = geocoder.reverse_many(points())
    next(results)
    assert consumed == 4096
    geocoder.close()
    geocoder.close()
    with pytest.raises(ClosedGeocoderError):
        next(results)
    for action in (
        lambda: geocoder.reverse(0, 0),
        geocoder.info,
        geocoder.__enter__,
        lambda: list(geocoder.reverse_many([])),
    ):
        with pytest.raises(ClosedGeocoderError):
            action()
    with Geocoder(FIXTURE) as reopened:
        assert reopened.reverse(52.37, 4.9)


def test_info_is_detached(geocoder: Geocoder) -> None:
    info = geocoder.info()
    assert info["resolution"] == 8
    assert info["city_cutoff_km"] == 50
    info["sources"].clear()
    assert geocoder.info()["sources"]


def test_discovery_and_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from thereabouts import DataNotInstalledError, api, reverse

    monkeypatch.delenv("THEREABOUTS_DATA", raising=False)
    for path in (None, tmp_path / "missing"):
        with pytest.raises(DataNotInstalledError, match="python -m build_data"):
            Geocoder(path)
    monkeypatch.setenv("THEREABOUTS_DATA", str(FIXTURE))
    monkeypatch.setattr(api, "_default", None)
    monkeypatch.setattr(api, "_default_pid", None)
    assert reverse(52.37, 4.9)
    assert api._default is not None
    api._default.close()
    with Geocoder() as selected:
        assert selected.reverse(52.37, 4.9)
    monkeypatch.setenv("THEREABOUTS_DATA", str(tmp_path / "missing"))
    with Geocoder(FIXTURE) as explicit:
        assert explicit.reverse(52.37, 4.9)

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from typing import cast

import numpy as np
import pytest

from pyofflinegeocoder import Geocoder

from .conftest import FIXTURE
from .oracle import HaversineOracle


@pytest.mark.parametrize(
    "lat,lon,code,admin",
    [
        (52.37, 4.9, "NL", "Noord-Holland"),
        (50.85, 4.35, "BE", "Brussels"),
        (49.61, 6.13, "LU", "Luxembourg"),
    ],
)
def test_benelux_containment(
    geocoder: Geocoder, lat: float, lon: float, code: str, admin: str
) -> None:
    result = geocoder.reverse(lat, lon)
    assert result.country.value is not None and result.country.value.code == code
    assert result.admin1.value is not None and result.admin1.value.name == admin
    assert result.country.method == result.admin1.method == "polygon"
    assert result.country.candidates == (result.country.value,)
    assert result.snapshot_id == geocoder.info().snapshot_id
    assert result.policy_id == geocoder.info().policy_id
    assert result.land_status == "inside_mask"
    assert result.place_status == "matched"
    with pytest.raises(FrozenInstanceError):
        result.latitude = 0  # type: ignore[misc]


@pytest.mark.parametrize(
    "lat,lon",
    [
        (True, 1),
        (10**1000, 1),
        (1, False),
        (float("nan"), 1),
        (1, float("inf")),
        (-float("inf"), 1),
        (90.01, 0),
        (-90.01, 0),
        (0, 180.01),
        (0, -180.01),
        ("50", 4),
        (None, 4),
        (1 + 2j, 4),
        (np.bool_(True), 4),
    ],
)
def test_invalid_coordinates_raise_value_error(
    geocoder: Geocoder, lat: object, lon: object
) -> None:
    with pytest.raises(ValueError):
        geocoder.reverse(cast(float, lat), cast(float, lon))


@pytest.mark.parametrize("cutoff", [-1, float("nan"), float("inf"), True, "50"])
def test_invalid_cutoffs_even_when_place_disabled(
    geocoder: Geocoder, cutoff: object
) -> None:
    with pytest.raises(ValueError):
        geocoder.reverse(
            50, 5, include_place=False, max_place_distance_km=cast(float, cutoff)
        )


def test_include_place_must_be_boolean(geocoder: Geocoder) -> None:
    with pytest.raises(ValueError):
        geocoder.reverse(50, 5, include_place=cast(bool, 1))


def test_endpoints_normalize_and_regional_coverage_is_unknown(
    geocoder: Geocoder,
) -> None:
    assert geocoder.reverse(0, 180) == geocoder.reverse(0, -180)
    for lat in (-90, 90):
        assert geocoder.reverse(lat, 0).land_status == "unknown"
    result = geocoder.reverse(48.99, 5)
    assert result.country.status == result.admin1.status == "no_coverage"
    assert result.place_status == "no_coverage"


def test_sea_is_outside_mapped_land(geocoder: Geocoder) -> None:
    result = geocoder.reverse(53, 3, max_place_distance_km=None)
    assert result.country.status == result.admin1.status == "not_applicable"
    assert result.land_status == "outside_mask"
    assert result.place_status == "outside_land"
    assert result.nearest_place is None


def test_distance_cutoff_is_inclusive_and_none_is_unlimited(
    synthetic: Geocoder,
) -> None:
    assert synthetic.reverse(1, 5).place_status == "beyond_distance"
    result = synthetic.reverse(1, 5, max_place_distance_km=None)
    assert result.nearest_place is not None
    distance = result.nearest_place.distance_km
    assert distance > 50
    assert (
        synthetic.reverse(1, 5, max_place_distance_km=distance).nearest_place
        == result.nearest_place
    )
    assert (
        synthetic.reverse(1, 5, max_place_distance_km=distance - 1e-8).place_status
        == "beyond_distance"
    )
    assert synthetic.reverse(1, 4, max_place_distance_km=0).place_status == "matched"


def test_disabled_places_keep_original_administration(geocoder: Geocoder) -> None:
    enabled = geocoder.reverse(50, 5)
    disabled = geocoder.reverse(50, 5, include_place=False)
    assert enabled.country == disabled.country
    assert enabled.admin1 == disabled.admin1
    assert disabled.nearest_place is None and disabled.place_status == "disabled"


def test_batch_preserves_order_and_does_not_read_ahead(geocoder: Geocoder) -> None:
    consumed: list[int] = []
    coordinates = [(50, 5), (52, 6), (53, 3)]

    def points() -> Iterator[tuple[float, float]]:
        for i, pair in enumerate(coordinates):
            consumed.append(i)
            yield pair

    results = geocoder.reverse_many(points())
    assert consumed == []
    assert next(results) == geocoder.reverse(*coordinates[0])
    assert consumed == [0]
    assert list(results) == [geocoder.reverse(*p) for p in coordinates[1:]]
    assert list(geocoder.reverse_many([])) == []


@pytest.mark.parametrize("bad", [(91, 0), (0,), (0, 1, 2), None])
def test_batch_raises_only_when_invalid_pair_is_reached(
    geocoder: Geocoder, bad: object
) -> None:
    pairs = cast(list[tuple[float, float]], [(50, 5), bad, (51, 5)])
    results = geocoder.reverse_many(pairs)
    assert next(results) == geocoder.reverse(50, 5)
    with pytest.raises(ValueError):
        next(results)


def test_batch_options_share_scalar_policy(geocoder: Geocoder) -> None:
    coordinates = [(50, 5), (53, 3)]
    assert list(
        geocoder.reverse_many(
            coordinates, include_place=False, max_place_distance_km=None
        )
    ) == [
        geocoder.reverse(*p, include_place=False, max_place_distance_km=None)
        for p in coordinates
    ]
    with pytest.raises(ValueError):
        next(geocoder.reverse_many([], max_place_distance_km=-1))


def test_nearest_matches_brute_force_haversine(geocoder: Geocoder) -> None:
    oracle = HaversineOracle(FIXTURE)
    rng = np.random.default_rng(104)
    checked = 0
    for lat, lon in rng.uniform([49, 2], [54, 8], (200, 2)):
        result = geocoder.reverse(float(lat), float(lon), max_place_distance_km=None)
        if result.land_status != "inside_mask":
            continue
        identity, distance = oracle.nearest(lat, lon)
        assert result.nearest_place is not None
        assert result.nearest_place.geoname_id == identity
        assert result.nearest_place.distance_km == pytest.approx(distance, abs=2e-9)
        checked += 1
    assert checked > 100


def test_concurrent_reads_and_lazy_initialization(geocoder: Geocoder) -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        answers = list(pool.map(lambda _: geocoder.reverse(50, 5), range(20)))
    assert all(answer == answers[0] for answer in answers)

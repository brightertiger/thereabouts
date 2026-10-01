from pathlib import Path

import numpy as np
import pytest

from pyofflinegeocoder import Geocoder

from .oracle import HaversineOracle

pytestmark = pytest.mark.world


@pytest.mark.parametrize(
    "lat,lon,code",
    [
        (0, 180, None),
        (90, 120, None),
        (-90, -170, "AQ"),
        (-90, 130, "AQ"),
        (-16.8, 179.9, None),
        (-16.9, 179.98, "FJ"),
        (-16.8, 180, "FJ"),
        (-16.8, -179.9, "FJ"),
        (66, 179.9, "RU"),
        (66, -179.9, "RU"),
    ],
)
def test_antimeridian_and_poles(
    world: Geocoder, lat: float, lon: float, code: str | None
) -> None:
    result = world.reverse(lat, lon, max_place_distance_km=None)
    if code is None:
        assert result.country.status == "not_applicable"
        assert result.land_status == "outside_mask"
    else:
        assert result.country.value is not None and result.country.value.code == code
        if code == "AQ":
            assert result.admin1.status == "not_applicable"
    if abs(lon) == 180:
        assert world.reverse(lat, -180) == world.reverse(lat, 180)


def test_world_nearest_matches_haversine_including_polar_and_dateline(
    world: Geocoder, world_path: Path
) -> None:
    oracle = HaversineOracle(world_path)
    rng = np.random.default_rng(984)
    coordinates = [(-90.0, 0.0), (66.0, 179.9), (66.0, -179.9), (78.0, 15.0)]
    coordinates.extend(
        (float(lat), float(lon))
        for lat, lon in rng.uniform([-90, -180], [90, 180], (120, 2))
    )
    checked = 0
    for lat, lon in coordinates:
        result = world.reverse(lat, lon, max_place_distance_km=None)
        if result.land_status != "inside_mask":
            continue
        identity, distance = oracle.nearest(lat, lon)
        assert result.nearest_place is not None
        assert result.nearest_place.geoname_id == identity
        assert result.nearest_place.distance_km == pytest.approx(distance, abs=1e-8)
        checked += 1
    assert checked > 25


def test_regional_settlement_subset_retains_global_nearest_at_edges(
    world: Geocoder, geocoder: Geocoder
) -> None:
    rng = np.random.default_rng(51)
    coordinates = list(rng.uniform([49, 2], [54, 8], (150, 2)))
    coordinates.extend([(49, 5), (54, 5), (51, 2), (51, 8)])
    for lat, lon in coordinates:
        regional = geocoder.reverse(float(lat), float(lon), max_place_distance_km=None)
        global_result = world.reverse(
            float(lat), float(lon), max_place_distance_km=None
        )
        assert regional.nearest_place == global_result.nearest_place
        assert regional.country == global_result.country
        assert regional.admin1 == global_result.admin1


def test_world_full_verification(world: Geocoder) -> None:
    world.verify()

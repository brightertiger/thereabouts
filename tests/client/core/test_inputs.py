"""Batch coordinates must be named, so latitude and longitude cannot be swapped."""

from pathlib import Path
from typing import Any

import pytest

from thereabouts import Geocoder
from thereabouts.results import Point

SAMPLE = Path(__file__).parents[2] / "fixtures/packs/core-sample"


@pytest.mark.parametrize("point", [(50.0, 4.0), [50.0, 4.0], {"lat": 50.0}, 50.0])
def test_reverse_many_rejects_unnamed_or_incomplete_points(point: Any) -> None:
    with Geocoder(SAMPLE) as geo, pytest.raises(TypeError, match="named lat and lon"):
        list(geo.reverse_many([point]))


def test_reverse_many_accepts_coordinate_attributes() -> None:
    with Geocoder(SAMPLE) as geo:
        result = next(geo.reverse_many([Point(50.8503, 4.3517)]))
        assert result.country is not None and result.country.code == "BE"

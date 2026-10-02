"""City footprints use the inherited spherical land projection offshore."""

from pathlib import Path

import numpy as np
import pytest
import shapely

from build_data.cities.projection import project
from build_data.reconcile.common import connect
from build_data.reconcile.spatial import create_areas, insert_area
from tests.test_city_normalization import city, make_engine


@pytest.mark.parametrize("original_boundary", [False, True])
def test_offshore_uses_city_on_projected_land(
    tmp_path: Path, original_boundary: bool
) -> None:
    land_path = tmp_path / "land.sqlite"
    db = connect(land_path)
    create_areas(db)
    shape = (
        shapely.box(0.03, -0.03, 0.06, 0.03)
        if original_boundary
        else shapely.box(-0.03, -0.03, 0.01, 0.03)
    )
    insert_area(db, "land", "land", 0, shape.wkb, shape.bounds, "test")
    db.commit()
    db.close()
    engine = make_engine(
        tmp_path,
        [city("coastal-city", 0, 5000000), city("far-neighbour", 0.2, 20000)],
        [
            {
                "city_id": "coastal-city",
                "priority": 0,
                "method": "city_polygon",
                "geometry": shapely.box(
                    -0.03, -0.03, 0.025 if original_boundary else 0.0099999999, 0.03
                ),
            }
        ],
    )
    engine.land = land_path, 15000
    coordinates = np.array([[0.0, 0.02]])
    wrong, _ = engine.overlay(coordinates, False)
    assert wrong.tolist() == ["coastal-city" if original_boundary else "far-neighbour"]
    actual, methods = engine.apply(
        coordinates,
        np.array(["coastal-city"], dtype=object),
        np.array(["area"], dtype=object),
        False,
        np.array([True]),
    )
    assert actual.tolist() == ["coastal-city"]
    assert methods.tolist() == ["city_polygon"]
    with pytest.raises(ValueError, match="land input"):
        project(None, coordinates, np.array([True]))

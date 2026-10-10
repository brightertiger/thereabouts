from __future__ import annotations

import math
from pathlib import Path

import pytest
import shapely

from pipeline.config.engines import EngineLimits
from pipeline.engines.geo.sphere import EARTH_M
from pipeline.engines.geo.windows import windows
from pipeline.engines.reconcile.land import Land
from pipeline.engines.store.areas import insert_area
from pipeline.engines.store.database import connect
from pipeline.engines.store.schema import create_areas


def test_offshore_cutoff_overlap_holes_and_dateline(tmp_path: Path) -> None:
    path = tmp_path / "land.sqlite"
    db = connect(path, cache_kib=EngineLimits().sqlite_cache_kib)
    create_areas(db)
    for i, geometry in enumerate(
        [
            shapely.box(-1, -1, 0, 1),
            shapely.box(-0.1, -1, 0, 1),
            shapely.Polygon(
                [(2, -1), (3, -1), (3, 1), (2, 1)],
                holes=[[(2.2, -0.5), (2.8, -0.5), (2.8, 0.5), (2.2, 0.5)]],
            ),
            shapely.box(-180, 10, -179.9, 11),
        ]
    ):
        insert_area(db, str(i), "land", 0, geometry.wkb, geometry.bounds, "test")
    db.commit()
    db.close()
    land = Land(path, limits=EngineLimits())
    try:
        degree = math.degrees(1 / EARTH_M)
        assert land.project(-0.05, 0, 1000) == (-0.05, 0, "land", 0.0)
        assert land.project(999 * degree, 0, 1000) is not None
        assert land.project(1001 * degree, 0, 1000) is None
        assert land.project(2.5, 0, 1000) is None
        q = land.project(179.999, 10.5, 1000)
        assert q and q[2] == "offshore" and q[3] < 200
        assert sum(1 for _ in windows((179.999, 10.5, 179.999, 10.5), 1000)) == 2
    finally:
        land.close()


@pytest.mark.parametrize("latitude", [0.0, 45.0, 80.0])
def test_spherical_distance_is_not_a_fixed_degree_buffer(
    tmp_path: Path, latitude: float
) -> None:
    path = tmp_path / "land.sqlite"
    db = connect(path, cache_kib=EngineLimits().sqlite_cache_kib)
    create_areas(db)
    shape = shapely.box(-1, latitude - 0.1, 0, latitude + 0.1)
    insert_area(db, "l", "land", 0, shape.wkb, shape.bounds, "test")
    db.commit()
    db.close()
    land = Land(path, limits=EngineLimits())
    try:
        x = math.degrees(900 / EARTH_M) / math.cos(math.radians(latitude))
        value = land.project(x, latitude, 1000)
        assert value and abs(value[3] - 900) < 0.1
    finally:
        land.close()

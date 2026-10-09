from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import shapely

from pipeline.config.engines import EngineLimits
from pipeline.engines.reconcile.entities import save_entity
from pipeline.engines.reconcile.lookup import Locator
from pipeline.engines.store.areas import insert_area
from pipeline.engines.store.codec import Row, pack
from pipeline.engines.store.database import connect
from pipeline.engines.store.entities import add_point
from pipeline.engines.store.schema import create_areas, create_entities


@pytest.fixture
def synthetic(tmp_path: Path) -> Iterator[tuple[Locator, dict[str, Path]]]:
    path, land_path = tmp_path / "ZZ.sqlite", tmp_path / "land.sqlite"
    db, land = (
        connect(path, cache_kib=EngineLimits().sqlite_cache_kib),
        connect(land_path, cache_kib=EngineLimits().sqlite_cache_kib),
    )
    create_areas(db)
    create_areas(land)
    create_entities(db)
    sea = shapely.Polygon(
        [(-1, -1), (0.5, -1), (0.5, 1), (-1, 1)],
        holes=[[(-0.15, -0.15), (-0.05, -0.15), (-0.05, 0.1), (-0.15, 0.1)]],
    )
    insert_area(land, "land", "land", 0, sea.wkb, sea.bounds, "test")
    for identity, role, shape, priority, population in [
        ("country:ZZ", "country", shapely.box(-1, -1, 1, 1), 0, None),
        ("state:west", "state", shapely.box(-1, -1, 0.1, 1), 0, None),
        ("state:east", "state", shapely.box(0.1, -1, 1, 1), 0, None),
        ("city:area", "city", shapely.box(-0.4, -0.4, 0.15, 0.25), 1, 100),
        ("city:overlap", "city", shapely.box(0, -0.3, 0.3, 0.2), 0, 10000),
        ("city:area", "city", shapely.box(-0.4, -0.4, 0.16, 0.3), 0, 100),
    ]:
        e: Row = {
            "id": identity,
            "role": role,
            "name": identity,
            "population": population,
            "geonames_id": identity,
            "country_code": "ZZ",
            "sovereign": None,
            "name_provenance": {"source": "test", "language": "en"},
        }
        save_entity(db, e)
        insert_area(
            db,
            identity,
            role,
            priority,
            shape.wkb,
            shape.bounds,
            pack({"source": "test", "source_id": identity}),
        )
    for identity, x, y in [
        ("city:nearest-a", 0.2, 0.5),
        ("city:nearest-b", -0.2, 0.5),
        ("city:nearest-c", 0.2, 0.5),
    ]:
        save_entity(
            db,
            {
                "id": identity,
                "role": "city",
                "name": identity,
                "population": 1,
                "geonames_id": identity,
                "country_code": "ZZ",
                "sovereign": None,
                "name_provenance": {"source": "test", "language": "en"},
            },
        )
        add_point(db, identity, x, y)
    db.commit()
    land.commit()
    db.close()
    land.close()
    paths = {"ZZ": path}
    with Locator(
        paths,
        land_path,
        {"offshore_m": 1000, "nearest_m": 50000},
        limits=EngineLimits(),
    ) as locator:
        yield locator, paths

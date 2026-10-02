"""Invalid region promotions fall back to a real rural settlement and cutoff."""

from pathlib import Path

import numpy as np
import shapely

from build_data.reconcile.common import connect
from build_data.reconcile.spatial import create_areas, insert_area
from tests.test_city_normalization import city, make_engine


def test_rejected_area_cannot_survive_as_rural_fallback(tmp_path: Path) -> None:
    engine = make_engine(
        tmp_path, [city("village", 0, 50)], [], shapely.box(10, 10, 11, 11)
    )
    db = connect(engine.source)
    create_areas(db)
    shape = shapely.box(-2, -2, 2, 2)
    insert_area(db, "region", "city", 0, shape.wkb, shape.bounds, "test")
    engine.rejected = {r[0] for r in db.execute("SELECT id FROM areas")}
    engine.repair_ids = {"region"}
    db.commit()
    db.close()
    ids, methods = engine.apply(
        np.array([[0.0, 0.001], [0.0, 0.4], [0.0, 0.5]]),
        np.array(["region"] * 3, dtype=object),
        np.array(["area"] * 3, dtype=object),
        False,
    )
    assert ids.tolist() == ["village", "village", None]
    assert methods.tolist() == ["rural_nearest", "rural_nearest_distant", None]

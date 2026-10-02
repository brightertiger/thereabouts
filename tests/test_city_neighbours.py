"""Rejected source boundaries must remain visible to independent neighbour checks."""

from pathlib import Path

import h3
import shapely

from build_data.cities.evaluate import Comparison
from build_data.cities.quality import neighbour_checks
from build_data.golden.reader import Cells
from build_data.golden.schemas import CELLS
from build_data.golden.storage import parquet
from build_data.golden_v2.gates import failures
from build_data.reconcile.common import connect
from build_data.reconcile.spatial import create_areas, insert_area
from tests.test_city_normalization import city, make_engine


def test_rejecting_a_town_boundary_cannot_hide_its_polygon_losses(
    tmp_path: Path,
) -> None:
    engine = make_engine(
        tmp_path, [city("town", 0, 20000), city("large", 0.08, 1000000)], []
    )
    db = connect(engine.source)
    create_areas(db)
    shape = shapely.box(-0.02, -0.02, 0.06, 0.02)
    insert_area(db, "town", "city", 0, shape.wkb, shape.bounds, "test")
    db.commit()
    db.close()
    root = h3.cell_to_parent(h3.latlng_to_cell(0, 0, 8), 3)
    table = parquet(
        tmp_path / "base.parquet",
        [
            {
                "h3": root,
                "h3_uint64": int(root, 16),
                "h3_resolution": 3,
                "country_id": "country:ZZ",
                "city_id": "town",
                "city_method": "area",
                "land_method": "land",
            }
        ],
        CELLS,
    )
    table.update(kind="cells", block=root)
    comparison = Comparison(Cells([table]), {"ZZ": engine}, False)
    report = neighbour_checks(comparison, "ZZ", engine, {"ZZ": {"town": "Town"}})[0]
    assert not report["accepted_city_footprint"]
    assert report["source_area_ids"]
    assert report["point_after"]["city_id"] == "town"
    assert report["polygon_before"]["expected"] > report["polygon_after"]["expected"]
    assert failures([{"footprints": [], "neighbours": [report]}], [])["neighbours"]

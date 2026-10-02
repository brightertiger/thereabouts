"""Rejected source boundaries must remain visible to independent neighbour checks."""

from pathlib import Path

import h3
import shapely

from build_data.cities.evaluate import Comparison
from build_data.cities.quality import neighbour_checks
from build_data.golden.reader import Cells
from build_data.golden.schemas import CELLS
from build_data.golden.storage import parquet
from build_data.normalize_cells.gates import failures
from build_data.reconcile.common import Row, connect
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


def test_all_boundaries_detect_losses_hidden_by_net_gains(tmp_path: Path) -> None:
    from build_data.cities.boundary_checks import boundary_checks
    from build_data.reconcile.common import pack

    engine = make_engine(tmp_path, [city("town", 0, 20000)], [])
    shape = shapely.box(-0.01, -0.01, 0.01, 0.01)
    db = connect(engine.index_path)
    db.execute("CREATE TABLE boundaries(id INT,geometry BLOB,data BLOB)")
    db.execute(
        "INSERT INTO boundaries VALUES(1,?,?)",
        (
            shape.wkb,
            pack(
                {
                    "city_id": "town",
                    "target_id": "town",
                    "method": "city_polygon",
                    "references": ["1"],
                }
            ),
        ),
    )
    db.commit()
    db.close()

    class ChangedComparison(Comparison):
        def query(self, cells: list[str]) -> tuple[list[Row], list[Row]]:
            before = [
                {
                    "country_id": "country:ZZ",
                    "cell_status": "matched",
                    "city_id": "town" if i == 0 else "other",
                }
                for i in range(len(cells))
            ]
            after = [
                {**r, "city_id": "other" if i == 0 else "town"}
                for i, r in enumerate(before)
            ]
            return before, after

    report = boundary_checks(ChangedComparison(Cells([]), {}, False), "ZZ", engine)[0]
    assert report["after"]["expected"] > report["before"]["expected"]
    assert report["lost_cells"] == 1
    assert report["lost_to"] == {"other": 1}
    # A reviewed identity alias must not hide the old owner's lost cells.
    db = connect(engine.index_path)
    db.execute(
        "UPDATE boundaries SET data=?",
        (
            pack(
                {
                    "city_id": "canonical",
                    "target_id": "canonical",
                    "method": "city_polygon",
                    "references": ["1"],
                }
            ),
        ),
    )
    db.commit()
    db.close()
    engine.policy["countries"]["ZZ"] = {"identity_aliases": {"town": "canonical"}}
    aliased = boundary_checks(ChangedComparison(Cells([]), {}, False), "ZZ", engine)[0]
    assert aliased["before"]["expected"] == 1
    assert aliased["lost_cells"] == 1
    assert aliased["before_owner_ids"] == ["canonical", "town"]

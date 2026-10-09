"""Rejected source boundaries must remain visible to independent neighbour checks."""

from pathlib import Path

import h3
import shapely

from pipeline.config.engines import EngineLimits
from pipeline.config.schema import H3
from pipeline.engines.artifact_io import parquet
from pipeline.engines.cells.reader import Cells
from pipeline.engines.cells.schemas import CELLS
from pipeline.engines.cities.evaluate import Comparison
from pipeline.engines.cities.gates import failures
from pipeline.engines.cities.quality import neighbour_checks
from pipeline.engines.store.areas import insert_area
from pipeline.engines.store.codec import Row
from pipeline.engines.store.database import connect
from pipeline.engines.store.schema import create_areas
from tests.pipeline.cities.test_city_normalization import city, make_engine


def test_rejecting_a_town_boundary_cannot_hide_its_polygon_losses(
    tmp_path: Path,
) -> None:
    engine = make_engine(
        tmp_path, [city("town", 0, 20000), city("large", 0.08, 1000000)], []
    )
    db = connect(engine.source, cache_kib=EngineLimits().sqlite_cache_kib)
    create_areas(db)
    shape = shapely.box(-0.02, -0.02, 0.06, 0.02)
    insert_area(db, "town", "city", 0, shape.wkb, shape.bounds, "test")
    db.commit()
    db.close()
    root = h3.cell_to_parent(h3.latlng_to_cell(0, 0, 8), 3)
    table = parquet(
        tmp_path,
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
        1024,
    )
    table.update(kind="cells", block=root, path=str(tmp_path / table["path"]))
    comparison = Comparison(
        Cells([table], grid=H3(), limits=EngineLimits()), {"ZZ": engine}, False
    )
    report = neighbour_checks(comparison, "ZZ", engine, {"ZZ": {"town": "Town"}})[0]
    assert not report["accepted_city_footprint"]
    assert report["source_area_ids"]
    assert report["point_after"]["city_id"] == "town"
    assert report["polygon_before"]["expected"] > report["polygon_after"]["expected"]
    assert failures([{"footprints": [], "neighbours": [report]}], [])["neighbours"]


def test_all_boundaries_detect_losses_hidden_by_net_gains(tmp_path: Path) -> None:
    from pipeline.engines.cities.boundary_checks import boundary_checks
    from pipeline.engines.store.codec import pack

    engine = make_engine(tmp_path, [city("town", 0, 20000)], [])
    shape = shapely.box(-0.01, -0.01, 0.01, 0.01)
    db = connect(engine.index_path, cache_kib=EngineLimits().sqlite_cache_kib)
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

    report = boundary_checks(
        ChangedComparison(Cells([], grid=H3(), limits=EngineLimits()), {}, False),
        "ZZ",
        engine,
    )[0]
    assert report["after"]["expected"] > report["before"]["expected"]
    assert report["lost_cells"] == 1
    assert report["lost_to"] == {"other": 1}
    # A reviewed identity alias must not hide the old owner's lost cells.
    db = connect(engine.index_path, cache_kib=EngineLimits().sqlite_cache_kib)
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
    aliased = boundary_checks(
        ChangedComparison(Cells([], grid=H3(), limits=EngineLimits()), {}, False),
        "ZZ",
        engine,
    )[0]
    assert aliased["before"]["expected"] == 1
    assert aliased["lost_cells"] == 1
    assert aliased["before_owner_ids"] == ["canonical", "town"]

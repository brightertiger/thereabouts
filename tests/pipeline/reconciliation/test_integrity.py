from __future__ import annotations

from pathlib import Path

import shapely

from pipeline.config.engines import EngineLimits
from pipeline.config.policies import reconcile as policy
from pipeline.engines.reconcile.matching import prepare_catalog
from pipeline.engines.reconcile.state_votes import votes
from pipeline.engines.store.areas import insert_area
from pipeline.engines.store.database import connect
from pipeline.engines.store.schema import create_areas

from .conftest import place, write_inputs


def test_state_votes_exclude_large_evaluation_places(tmp_path: Path) -> None:
    small = [place(str(i), "Small", 0.5, 0.5, population=10) for i in range(10)]
    large = place("large", "Large", 0.5, 0.5, population=100000)
    large["admin1_code"] = "99"
    root = write_inputs(
        tmp_path / "in", geonames=[*small, large], divisions=[], areas=[]
    )
    db = connect(tmp_path / "states.sqlite", cache_kib=EngineLimits().sqlite_cache_kib)
    try:
        prepare_catalog(db, root, EngineLimits().source_batch_rows)
        create_areas(db)
        geometry = shapely.box(0, 0, 1, 1)
        insert_area(db, "state", "state", 0, geometry.wkb, geometry.bounds, "test")
        evidence = votes(
            db, "state", policy(), batch_rows=EngineLimits().state_vote_batch_rows
        )
        assert evidence["geonames_admin1"] == "01"
        assert evidence["evidence_counts"] == {"01": 10}
        assert evidence["large_places_excluded"]
    finally:
        db.close()

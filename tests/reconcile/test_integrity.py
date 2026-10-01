from __future__ import annotations

from pathlib import Path

import pytest
import shapely

from build_data.acquire import Ledger, Workspace
from build_data.reconcile.common import connect, policy
from build_data.reconcile.manifest import load, publish, status
from build_data.reconcile.matching import prepare_catalog
from build_data.reconcile.spatial import create_areas, insert_area
from build_data.reconcile.state_votes import votes

from .conftest import place, write_inputs


def test_manifest_rejects_corruption_before_and_after_publication(
    tmp_path: Path,
) -> None:
    workspace = Workspace(tmp_path)
    land, country = tmp_path / "land.sqlite", tmp_path / "ZZ.sqlite"
    land.write_bytes(b"validated land")
    country.write_bytes(b"validated country")
    ledger = Ledger(workspace.ledger_path)
    ledger.complete("reconcile.land", "world", "land-input", [land])
    ledger.complete("reconcile.country", "ZZ", "country-input", [country])
    publish(workspace, {"ZZ": country}, land, {}, {}, {}, "test")
    assert load(workspace)["countries"]["ZZ"]["size"] == country.stat().st_size
    manifest = workspace.root / "reconciled" / "manifest.json"
    before = manifest.read_bytes()
    country.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Unverified"):
        publish(workspace, {"ZZ": country}, land, {}, {}, {}, "test")
    assert manifest.read_bytes() == before
    with pytest.raises(ValueError, match="verification"):
        load(workspace)


def test_status_does_not_initialize_missing_workspace(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    assert not status(Workspace(root))["manifest_committed"]
    assert not root.exists()


def test_state_votes_exclude_large_evaluation_places(tmp_path: Path) -> None:
    small = [place(str(i), "Small", 0.5, 0.5, population=10) for i in range(10)]
    large = place("large", "Large", 0.5, 0.5, population=100000)
    large["admin1_code"] = "99"
    root = write_inputs(
        tmp_path / "in", geonames=[*small, large], divisions=[], areas=[]
    )
    db = connect(tmp_path / "states.sqlite")
    try:
        prepare_catalog(db, root)
        create_areas(db)
        geometry = shapely.box(0, 0, 1, 1)
        insert_area(db, "state", "state", 0, geometry.wkb, geometry.bounds, "test")
        evidence = votes(db, "state", policy())
        assert evidence["geonames_admin1"] == "01"
        assert evidence["evidence_counts"] == {"01": 10}
        assert evidence["large_places_excluded"]
    finally:
        db.close()

from __future__ import annotations

import json
from pathlib import Path

from pipeline.config.policies import reconcile as policy
from pipeline.engines.reconcile.classification import trusted_city
from pipeline.engines.reconcile.common import connect
from pipeline.engines.reconcile.matching import (
    default_perspective,
    link,
    prepare_catalog,
)

from .conftest import place, write_inputs


def test_ambiguous_name_does_not_merge_and_shared_id_wins(tmp_path: Path) -> None:
    root = write_inputs(
        tmp_path / "input",
        geonames=[
            place("1", "Springfield", 0.0, 0.0),
            place("2", "Springfield", 0.001, 0.0),
            place("3", "Unique", 1.0, 1.0),
        ],
        divisions=[],
        areas=[],
    )
    db = connect(tmp_path / "catalog.sqlite")
    try:
        prepare_catalog(db, root)
        row = place("ov", "Springfield", 0.0005, 0, source="overture")
        linked, method, _, issue = link(db, row, policy())
        assert linked is None and method == "unlinked" and issue
        db.execute("INSERT INTO wikidata VALUES('Q1','1')")
        row["provenance"] = json.dumps({"upstream": {"wikidata": "Q1"}})
        assert link(db, row, policy())[:2] == ("1", "wikidata")
        row["longitude"] = 100
        assert link(db, row, policy())[0] is None
        row = place("ov2", "Unique", 1.001, 1, source="overture")
        assert link(db, row, policy())[:2] == ("3", "names")
    finally:
        db.close()


def test_default_perspective() -> None:
    row = {"provenance": json.dumps({"upstream": {"perspectives": None}})}
    assert default_perspective(row)
    row["provenance"] = json.dumps({"upstream": {"perspectives": {"includes": ["XX"]}}})
    assert not default_perspective(row)


def test_strong_city_identity_can_cross_check_a_conflicting_feature_code() -> None:
    row = place("ov", "City", 0, 0, source="overture")
    row["feature_class"] = "city"
    match = place("gn", "City", 0, 0, code="PPLX")
    assert not trusted_city(row, match, {"method": "names"}, policy())
    link = {"method": "wikidata"}
    assert trusted_city(row, match, link, policy())
    assert "classification_conflict" in link
    row["subtype"] = "neighborhood"
    assert not trusted_city(row, match, link, policy())
    row["subtype"] = "locality"
    match["feature_code"] = "PPLH"
    assert not trusted_city(row, match, link, policy())

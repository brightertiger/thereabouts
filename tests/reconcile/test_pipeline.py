from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.config.policies import reconcile as policy
from pipeline.engines.reconcile.common import connect
from pipeline.engines.reconcile.lookup import Locator
from pipeline.engines.reconcile.spatial import create_areas, insert_area
from pipeline.runtime.jsonio import sha256_file
from tests.reconcile.conftest import reconciled

from .conftest import area, place, write_inputs


def test_nested_population_separate_state_and_resumption(tmp_path: Path) -> None:
    workspace = tmp_path
    root = write_inputs(
        tmp_path / "inputs",
        geonames=[
            place("1", "City", 0.5, 0.5, population=100000),
            place("2", "Ward", 0.51, 0.51, population=10000, code="PPLX"),
            place("3", "State", 0.5, 0.5, code="ADM1"),
        ],
        divisions=[
            place("c", "City", 0.5, 0.5, source="overture"),
            place("w", "Ward", 0.51, 0.51, source="overture"),
            place("s", "State", 0.5, 0.5, source="overture", subtype="region"),
        ],
        areas=[
            area("country", "Country", "country", (0, 0, 2, 2)),
            area("s", "State", "region", (0, 0, 2, 2)),
            area("c", "City", "locality", (0.1, 0.1, 1, 1)),
            area("w", "Ward", "locality", (0.4, 0.4, 0.6, 0.6)),
        ],
    )
    output = reconciled(workspace, root, "ZZ", policy())
    land = tmp_path / "land.sqlite"
    db = connect(land)
    create_areas(db)
    shape = area("land", "land", "land", (0, 0, 2, 2))
    insert_area(db, "land", "land", 0, shape["geometry"], (0, 0, 2, 2), "test")
    db.commit()
    db.close()
    with Locator({"ZZ": output}, land, policy()) as oracle:
        result = oracle.locate(0.51, 0.51)
        assert result["city"]["name"] == "City"
        assert result["state"]["name"] == "State"
        assert result["country"]["country_code"] == "ZZ"
        assert result["city_method"] == "area"
        assert result["city"]["parent"] == result["state"]["id"]
        assert result["city"]["code"] is None
        assert oracle.locate(1.1, 1.1)["city"] is None  # >50 km from every place
        assert not oracle.locate(5, 5)["eligible"]
        with pytest.raises(ValueError):
            oracle.locate(float("nan"), 1)
    digest = sha256_file(output)
    assert reconciled(workspace, root, "ZZ", policy()) == output
    output.write_bytes(b"corrupt")
    reconciled(workspace, root, "ZZ", policy())
    assert sha256_file(output) == digest


def test_country_failure_does_not_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_inputs(tmp_path / "inputs", geonames=[], divisions=[], areas=[])

    def fail(*args: object) -> None:
        raise OSError("injected interrupted area unit")

    monkeypatch.setattr("pipeline.engines.reconcile.build.assign_areas", fail)
    with pytest.raises(OSError, match="interrupted"):
        reconciled(tmp_path, root, "ZZ", policy())
    assert not list((tmp_path / "reconciled").rglob("*.sqlite"))
    assert not list((tmp_path / "reconciled").rglob("*.part"))

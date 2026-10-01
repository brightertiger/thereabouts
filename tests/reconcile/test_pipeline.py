from __future__ import annotations

from pathlib import Path

import pytest

from build_data.acquire import Workspace
from build_data.acquire.io import sha256_file
from build_data.reconcile.build import build_country
from build_data.reconcile.common import connect, policy
from build_data.reconcile.lookup import Locator
from build_data.reconcile.spatial import create_areas, insert_area

from .conftest import area, place, write_inputs


def test_nested_population_separate_state_and_resumption(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
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
    output = build_country(workspace, root, "ZZ", "inputs", policy(), "test")
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
    digest, modified = sha256_file(output), output.stat().st_mtime_ns
    assert build_country(workspace, root, "ZZ", "inputs", policy(), "test") == output
    assert output.stat().st_mtime_ns == modified
    output.write_bytes(b"corrupt")
    build_country(workspace, root, "ZZ", "inputs", policy(), "test")
    assert sha256_file(output) == digest


def test_country_failure_does_not_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_inputs(tmp_path / "inputs", geonames=[], divisions=[], areas=[])

    def fail(*args: object) -> None:
        raise OSError("injected interrupted area unit")

    monkeypatch.setattr("build_data.reconcile.build.assign_areas", fail)
    with pytest.raises(OSError, match="interrupted"):
        build_country(Workspace(tmp_path), root, "ZZ", "inputs", policy(), "test")
    assert not list((tmp_path / "reconciled").rglob("*.sqlite"))
    assert not list((tmp_path / "reconciled").rglob("*.part"))

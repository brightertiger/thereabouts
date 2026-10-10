"""Stable upstream identities replace build-local source area sequence IDs."""

import json
import sqlite3
from pathlib import Path

import pytest
import shapely

from pipeline.engines.store.areas import insert_area
from pipeline.engines.store.codec import Row, pack
from pipeline.engines.store.origins import boundary_origins, origin, resolver
from pipeline.engines.store.schema import create_areas

KIB = 1024


def overture(record: str, part: int = 0) -> Row:
    """An Overture area part whose geometry came from one upstream record."""
    sources = [
        {"property": "", "provider": "osm", "record_id": record},
        {
            "property": "/properties/names/common/en",
            "provider": "osm",
            "record_id": "n1@3",
        },
    ]
    return {
        "source": "overture",
        "source_id": "gers-" + record,
        "provenance": json.dumps(
            {"geometry_part": part, "upstream": {"sources": sources}}
        ),
    }


def test_origin_is_the_whole_feature_record_without_its_version() -> None:
    assert origin(overture("r134579@9")) == "osm:r134579"
    assert origin(overture("w1276063111@1", part=2)) == "osm:w1276063111#2"
    native = {
        "source": "geoboundaries",
        "source_id": "GBR-ADM2-1",
        "provenance": json.dumps({"geometry_part": 0}),
    }
    assert origin(native) == "geoboundaries:GBR-ADM2-1"
    with pytest.raises(ValueError, match="no upstream record"):
        origin({"provenance": "{}"})


def database(path: Path, records: list[str]) -> list[str]:
    """Store areas in the given order; return each record's new sequence ID."""
    db = sqlite3.connect(path)
    create_areas(db)
    shape = shapely.box(0, 0, 1, 1)
    for record in records:
        insert_area(
            db, "city", "city", 20, shape.wkb, shape.bounds, pack(overture(record))
        )
    ids = [str(i) for (i,) in db.execute("SELECT id FROM areas ORDER BY id")]
    db.commit()
    db.close()
    return ids


def test_a_rebuild_that_renumbers_areas_resolves_the_same_origins(
    tmp_path: Path,
) -> None:
    before = database(tmp_path / "before.sqlite", ["x@1", "r1@9", "w2@1"])
    after = database(tmp_path / "after.sqlite", ["w2@4", "y@1", "z@1", "r1@10"])
    old = boundary_origins(tmp_path / "before.sqlite", before[1:], KIB)
    new = boundary_origins(tmp_path / "after.sqlite", [after[3], after[0]], KIB)
    assert old == new == ["osm:r1", "osm:w2"]
    # A city-state boundary names its identity, not a stored area.
    assert boundary_origins(tmp_path / "missing.sqlite", ["city:country:SG"], KIB) == [
        "city:country:SG"
    ]
    with pytest.raises(ValueError, match="missing source area 99"):
        boundary_origins(tmp_path / "after.sqlite", ["99"], KIB)
    resolve = resolver(lambda cc: tmp_path / f"{cc}.sqlite", KIB)
    assert resolve({"country": "after", "references": after[:1]}) == ["osm:w2"]

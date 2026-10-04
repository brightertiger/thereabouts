"""Retained source interpretation decisions using the new adapters."""

import json
from collections import Counter
from typing import Any

import pyarrow as pa
import pytest
import shapely
from shapely.geometry import Polygon, box

from pipeline.config.schema import H3
from pipeline.config.sources import SourceLimits
from pipeline.sources.overture import areas as overture_areas
from pipeline.sources.overture import rows as overture_rows
from pipeline.sources.shared.geometry import split_geometry
from pipeline.sources.shared.schemas import SCHEMAS, validate_table

CONTEXT = {
    "source_url": "https://example.test/object",
    "source_release": "test-1",
    "license": "ODbL-1.0",
    "license_url": "https://example.test/license",
    "attribution": "Overture",
}


def division(
    identifier: str = "point-1", subtype: str = "neighborhood"
) -> dict[str, Any]:
    return {
        "id": identifier,
        "geometry": shapely.Point(-74.0060, 40.7128).wkb,
        "names": {
            "primary": "  Cafe\u0301\t町 ",
            "common": [("en", "Test Place")],
            "rules": [{"value": "Old Test", "variant": "historic", "language": "en"}],
        },
        "subtype": subtype,
        "class": "suburb",
        "admin_level": 3,
        "country": "US",
        "region": "US-NY",
        "parent_division_id": None,
        "hierarchies": [[{"division_id": identifier, "subtype": subtype}]],
        "perspectives": {"disputed_by": ["XX"]},
        "population": 0,
        "sources": [{"dataset": "Synthetic", "record_id": "source-1"}],
    }


def area(identifier: str = "area-1") -> dict[str, Any]:
    return {
        "id": identifier,
        "division_id": "point-1",
        "geometry": box(-75, 40, -73, 42).wkb,
        "names": {"primary": "Area", "common": [("en", "Test Area")]},
        "subtype": "neighborhood",
        "class": "land",
        "country": "US",
        "region": "US-NY",
        "admin_level": 3,
        "is_land": True,
        "is_territorial": True,
    }


def test_all_roles_names_and_nested_metadata_are_preserved(
    limits: SourceLimits,
) -> None:
    for subtype in (
        "country",
        "dependency",
        "region",
        "locality",
        "borough",
        "microhood",
        "future-subtype",
    ):
        raw = division(subtype=subtype)
        row = overture_rows.place(raw, CONTEXT)
        assert row["kind"] == subtype
        assert row["name"] == "Café 町"
        assert row["name_en"] == "Test Place"
        assert row["population"] == 0
        assert row["feature_class"] == "suburb"
        provenance = json.loads(row["provenance"])
        assert provenance["upstream"]["hierarchies"] == raw["hierarchies"]
        assert provenance["upstream"]["admin_level"] == 3
        validate_table(
            pa.Table.from_pylist([row], schema=SCHEMAS["places"]),
            "places",
            "overture",
            limits,
            grid=H3(),
        )
    aliases = list(overture_rows.names(raw, CONTEXT))
    assert [row["name_kind"] for row in aliases] == ["primary", "common", "historic"]
    assert aliases[-1]["is_historic"] is True
    assert aliases[0]["language"] is None
    assert aliases == list(overture_rows.names(raw, CONTEXT))
    validate_table(
        pa.Table.from_pylist(aliases, schema=SCHEMAS["names"]),
        "names",
        "overture",
        limits,
        grid=H3(),
    )


def test_ascii_primary_is_not_assumed_english() -> None:
    raw = division()
    raw["names"] = {"primary": "ASCII name"}
    assert overture_rows.place(raw, CONTEXT)["name_en"] is None


def test_repair_split_flags_ids_and_containment(
    monkeypatch: pytest.MonkeyPatch, limits: SourceLimits
) -> None:
    raw = area()
    raw["geometry"] = Polygon(
        [(-75, 40), (-73, 42), (-75, 42), (-73, 40), (-75, 40)]
    ).wkb
    stats: Counter[str] = Counter()
    converted = list(
        overture_areas.areas(
            raw, CONTEXT, "parent-1", stats, SourceLimits().row_bytes, 32
        )
    )
    assert stats["invalid_input"] == stats["repaired_input"] == 1
    assert all(
        row["source_id"] == "area-1" and row["entity_id"] == "point-1"
        for row in converted
    )
    assert converted[0]["parent_source_id"] == "parent-1"
    assert converted[0]["is_land"] and converted[0]["is_territorial"]
    validate_table(
        pa.Table.from_pylist(converted, schema=SCHEMAS["areas"]),
        "areas",
        "overture",
        limits,
        grid=H3(),
    )
    geometry = shapely.MultiPolygon([box(0, 0, 1, 1), box(2, 2, 3, 3)])
    parts = list(split_geometry(geometry, 160, max_depth=24))
    assert len(parts) == 2
    assert shapely.unary_union(parts).equals(geometry)


@pytest.fixture
def limits() -> SourceLimits:
    return SourceLimits()

"""Retained source interpretation decisions using the new adapters."""

import io
import json

import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from pipeline.sources.geoboundaries import geojson as scan
from pipeline.sources.shared.geometry import repair_geometry, split_geometry


def test_split_preserves_area_and_holes(monkeypatch: pytest.MonkeyPatch) -> None:
    polygon = Point(0, 0).buffer(10, quad_segs=64).difference(box(-2, -2, 2, 2))
    pieces = list(split_geometry(polygon, 700, flatten_intersections=True))
    assert len(pieces) > 1
    assert all(piece.is_valid and len(piece.wkb) <= 700 for piece in pieces)
    assert unary_union(pieces).symmetric_difference(polygon).area < 1e-10
    multi = MultiPolygon([box(i * 2, 0, i * 2 + 1, 1) for i in range(40)])
    parts = list(split_geometry(multi, 700, flatten_intersections=True))
    assert unary_union(parts).equals(multi)
    assert all(len(part.wkb) <= 700 for part in parts)


def test_bounds_and_empty_geometry_rejects() -> None:
    with pytest.raises(ValueError, match="Empty"):
        repair_geometry(Polygon(), clip_roundoff=True)
    with pytest.raises(ValueError, match="outside WGS84"):
        repair_geometry(box(179, 0, 181, 1), clip_roundoff=True)
    repaired, changes = repair_geometry(box(179, 0, 180 + 1e-10, 1), clip_roundoff=True)
    assert repaired.bounds[2] == 180
    assert changes == ["clip_sub_1e-8_degree_world_bound_roundoff"]


def test_geojson_id_audit_crosses_chunks_and_ignores_geometry_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[1, 2], [3, 4]]]},
                "properties": {
                    "shapeName": 'shapeID "not-an-id" {}[]',
                    "shapeID": "a\\b",
                },
            },
            {
                "properties": {"shapeID": "second", "shapeName": "shapeID"},
                "geometry": {"coordinates": []},
            },
        ],
    }
    assert scan.feature_ids(io.BytesIO(json.dumps(payload).encode()), 7, 8192) == [
        "a\\b",
        "second",
    ]
    with pytest.raises(ValueError, match=r"Unterminated|Incomplete"):
        scan.feature_ids(
            io.BytesIO(b'{"features": [{"properties": {"shapeID": "cut'), 7, 8192
        )

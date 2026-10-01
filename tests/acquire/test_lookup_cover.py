"""Adaptive compaction is equivalent to explicit fine-cell center membership."""

from pathlib import Path

import h3.api.basic_int as h3i
import pytest
import shapely
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry

from build_data.acquire.lookup_h3_cover import compact, cover


@pytest.mark.parametrize(
    "geometry",
    [
        box(-20, -5, 20, 10),
        box(-180, 80, 180, 90),
        box(-180, -90, 180, -80),
        MultiPolygon([box(175, -10, 180, 10), box(-180, -10, -175, 10)]),
        Polygon(
            [(-20, -20), (20, -20), (20, 20), (-20, 20)],
            holes=[[(-5, -5), (5, -5), (5, 5), (-5, 5)]],
        ),
    ],
)
def test_compact_world_center_coverage(geometry: BaseGeometry) -> None:
    resolution = 3
    expected = {
        cell
        for root in h3i.get_res0_cells()
        for cell in h3i.cell_to_children(root, resolution)
        if shapely.intersects_xy(geometry, *reversed(h3i.cell_to_latlng(cell)))
    }
    result = cover(geometry, resolution)
    assert set(h3i.uncompact_cells(result, resolution)) == expected
    assert len(result) < len(expected)
    assert compact(set(result), resolution) == set(result)
    assert all(
        h3i.is_valid_cell(cell) and h3i.get_resolution(cell) <= resolution
        for cell in result
    )


def test_finest_resolution_holes_and_tiny_islands() -> None:
    geometry = Polygon(
        [(77.4, 12.8), (77.8, 12.8), (77.8, 13.2), (77.4, 13.2)],
        holes=[[(77.5, 12.9), (77.6, 12.9), (77.6, 13.0), (77.5, 13.0)]],
    )
    result = cover(geometry)
    assert set(h3i.uncompact_cells(result, 8)) == set(
        h3i.geo_to_cells(geometry.__geo_interface__, 8)
    )
    assert cover(box(0, 0, 0.00000001, 0.00000001)) == []


def test_pentagon_compacts_six_children() -> None:
    parent = h3i.get_pentagons(2)[0]
    assert compact(set(h3i.cell_to_children(parent, 3)), 3) == {parent}


def test_world_coverage_counts_overlap_without_expansion(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from build_data.acquire.lookup_coverage_audit import world_coverage

    root = h3i.get_pentagons(0)[0]
    child = h3i.cell_to_center_child(root, 5)
    path = tmp_path / "cells.parquet"
    pq.write_table(
        pa.table({"h3_uint64": pa.array([root, child], type=pa.uint64())}), path
    )
    result = world_coverage([path])
    assert result["world_cells"] == h3i.get_num_cells(8)
    assert result["covered_cells"] == h3i.cell_to_children_size(root, 8)
    assert result["duplicate_memberships"] == h3i.cell_to_children_size(child, 8)

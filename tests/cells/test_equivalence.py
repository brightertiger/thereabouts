from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from h3.api import basic_int as h3

from pipeline.config.schema import H3
from pipeline.engines.cells.compaction import compact
from pipeline.engines.cells.oracle import Oracle
from pipeline.engines.cells.reader import interval
from pipeline.engines.hierarchy import descendants, label_block
from pipeline.engines.reconcile.lookup import Locator


def test_every_finest_centre_equals_independent_scalar_and_compacted_ancestors(
    synthetic: tuple[Locator, dict[str, Path]],
) -> None:
    locator, paths = synthetic
    cells, coordinates = descendants(h3.latlng_to_cell(0, 0, 3), 8)
    bounds = (
        coordinates[:, 1].min(),
        coordinates[:, 0].min(),
        coordinates[:, 1].max(),
        coordinates[:, 0].max(),
    )
    oracle = Oracle(locator, paths, bounds)
    labels = label_block(oracle, cells, coordinates, 8)
    direct = oracle.labels(coordinates)
    assert np.array_equal(labels, direct)
    stored, values = compact(cells, labels, grid=H3())
    table = dict(zip(stored, values, strict=True))
    for cell, point, value in zip(cells, coordinates, labels, strict=True):
        answer = locator.locate(*point)
        expected = (
            *(
                answer[k]["id"] if answer[k] else None
                for k in ("country", "state", "city")
            ),
            answer["city_method"],
            answer["land_method"],
        )
        assert oracle.answers[int(value)] == expected
        found = [
            table[p]
            for level in range(3, 9)
            if (p := h3.cell_to_parent(int(cell), level)) in table
        ]
        assert found == ([value] if value else [])
    assert len(stored) < np.count_nonzero(labels)
    assert {a[3] for a in oracle.answers} >= {None, "area", "nearest"}
    assert {a[4] for a in oracle.answers} >= {None, "land", "offshore"}


@pytest.mark.parametrize("root", h3.get_pentagons(3))
def test_pentagons_and_integer_ranges_cover_only_actual_descendants(root: int) -> None:
    cells, _ = descendants(root, 8)
    labels = np.ones(len(cells), dtype=np.uint64)
    stored, values = compact(cells, labels, grid=H3())
    assert stored.tolist() == [root]
    assert values.tolist() == [1]
    lo, hi = interval(root, 3, H3().cell_resolution)
    assert all(lo <= int(c) <= hi for c in cells)
    assert len(cells) == h3.cell_to_children_size(root, 8)
    for r in range(3, 9):
        children = h3.cell_to_children(root, r)
        previous = -1
        for child in children:
            low, high = interval(child, r, H3().cell_resolution)
            assert low > previous
            previous = high


def test_nearest_ties_and_offshore_cutoff(
    synthetic: tuple[Locator, dict[str, Path]],
) -> None:
    locator, paths = synthetic
    coordinates = np.array(
        [[0.5, 0], [0.5, 0.2], [0.6, 0.505], [0.6, 0.515]], dtype=np.float64
    )
    oracle = Oracle(locator, paths, (-0.2, 0.4, 0.6, 0.7))
    values = oracle.labels(coordinates)
    for point, value in zip(coordinates, values, strict=True):
        answer = locator.locate(*point)
        assert oracle.answers[int(value)] == (
            *(
                answer[k]["id"] if answer[k] else None
                for k in ("country", "state", "city")
            ),
            answer["city_method"],
            answer["land_method"],
        )

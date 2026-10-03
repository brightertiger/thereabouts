"""Exhaustive flat-resolution-8 equivalence, including ocean descendants."""

from pathlib import Path

import numpy as np
from h3.api import basic_int as h3

from pipeline.engines.hierarchy import blocks, compact, descendants, label_block
from tests.support.reference.oracle import Reference
from thereabouts.table import Table

from .conftest import FIXTURE

REFERENCE = FIXTURE.with_name("reference")


def test_every_benelux_leaf_equals_brute_force_flat_table() -> None:
    reference = Reference(REFERENCE)
    combined = Table(FIXTURE)
    checked = 0
    covered: set[int] = set()
    try:
        for root in blocks(reference.pack.manifest["coverage_bbox"]):
            cells, coordinates = descendants(root, 8)
            flat = reference.labels(coordinates)  # Every centre, no certificates.
            assert np.array_equal(label_block(reference, cells, coordinates, 8), flat)
            assert np.array_equal(combined.labels(cells), flat)
            assert [
                combined.lookup_one(int(cell)) for cell in cells
            ] == reference.locations(flat)
            checked += len(cells)
            covered.update(map(int, cells))
        assert checked == 554631
        # An independent finest-resolution fill checks regional root coverage.
        polygon = h3.LatLngPoly([(49, 2), (49, 8), (54, 8), (54, 2)])
        assert set(h3.polygon_to_cells(polygon, 8)) <= covered
    finally:
        reference.close()
        combined.close()


def test_batch_oracle_matches_scalar_predicates() -> None:
    reference = Reference(REFERENCE)
    rng = np.random.default_rng(49)
    coordinates = rng.uniform([49, 2], [54, 8], (1000, 2))
    try:
        assert reference.locations(reference.labels(coordinates)) == [
            reference.scalar(*p) for p in coordinates
        ]
    finally:
        reference.close()


def test_pentagon_compaction_keeps_all_six_children() -> None:
    for root in h3.get_pentagons(3):
        cells, _ = descendants(root, 8)
        labels = np.full(len(cells), 17, dtype=np.uint64)
        keys, values = compact(cells, labels, 8)
        assert list(keys) == [0]
        assert list(values) == [17]
        labels[-1] = 19
        keys, values = compact(cells, labels, 8)
        assert 0 not in keys
        assert 19 in values


def test_certificates_include_tiny_interior_islands(synthetic_pack: Path) -> None:
    reference = Reference(synthetic_pack)
    try:
        # The small island lies away from the rectangle centre and corners.
        _, certain = reference.certify(np.array([[18.9, 18.9, 19.2, 19.2]]))
        assert not certain[0]
    finally:
        reference.close()


def test_fixture_build_is_reproducible_and_atomic(tmp_path: Path) -> None:
    from pipeline.runtime.jsonio import sha256_file as sha256
    from tests.support.table import build_table

    output = tmp_path / "copy"
    build_table(REFERENCE, output)
    for file in FIXTURE.iterdir():
        assert sha256(file) == sha256(output / file.name)
    import pytest

    with pytest.raises(FileExistsError):
        build_table(REFERENCE, output)


def test_closed_regional_bounds_include_centres_on_edges() -> None:
    cell = h3.latlng_to_cell(52.37, 4.9, 8)
    lat, lon = h3.cell_to_latlng(cell)
    roots = set(blocks([lon, lat, lon + 1e-6, lat + 1e-6]))
    assert h3.cell_to_parent(cell, 3) in roots

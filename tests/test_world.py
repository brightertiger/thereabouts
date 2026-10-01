"""Explicit world-table tests: polar, dateline and random leaf equivalence."""

from pathlib import Path

import numpy as np
import pytest
from h3.api import basic_int as h3

from build_data.hierarchy import descendants, label_block
from build_data.reference.oracle import Reference
from pyofflinegeocoder import Geocoder
from pyofflinegeocoder.table import Table

pytestmark = pytest.mark.world


def test_world_random_and_special_points(world: Geocoder, world_path: Path) -> None:
    reference = Reference(Path("data/reference"))
    rng = np.random.default_rng(984)
    coordinates = rng.uniform([-90, -180], [90, 180], (10000, 2))
    coordinates = np.vstack(
        (
            coordinates,
            [
                (90, 0),
                (-90, 0),
                (66, 179.9),
                (66, -179.9),
                (78, 15),
                (0, 180),
                (0, -180),
            ],
        )
    )
    resolution = world.info()["resolution"]
    centres = np.array(
        [h3.cell_to_latlng(h3.latlng_to_cell(*p, resolution)) for p in coordinates]
    )
    try:
        expected = reference.locations(reference.labels(centres))
        assert list(world.reverse_many(map(tuple, coordinates))) == expected
        assert [world.reverse(*point) for point in coordinates] == expected
        table = Table(world_path)
        cells = np.array(
            [h3.latlng_to_cell(*p, resolution) for p in coordinates], dtype=np.uint64
        )
        assert table.lookup(cells) == expected
        table.close()
        assert reference.locations(reference.labels(coordinates[:100])) == [
            reference.scalar(*p) for p in coordinates[:100]
        ]
    finally:
        reference.close()


def test_world_certificates_at_pentagons_and_seam(world: Geocoder) -> None:
    reference = Reference(Path("data/reference"))
    resolution = world.info()["resolution"]
    roots = [
        *h3.get_pentagons(3),
        h3.latlng_to_cell(0, 180, 3),
        h3.latlng_to_cell(90, 0, 3),
        h3.latlng_to_cell(-90, 0, 3),
    ]
    try:
        for root in roots:
            cells, coordinates = descendants(root, resolution)
            assert np.array_equal(
                label_block(reference, cells, coordinates, resolution),
                reference.labels(coordinates),
            )
    finally:
        reference.close()


def test_world_nearest_against_independent_haversine(world_path: Path) -> None:
    from .oracle import HaversineOracle

    reference = Reference(Path("data/reference"))
    oracle = HaversineOracle(Path("data/reference"))
    coordinates = np.array(
        [(78, 15), (66, 179.9), (66, -179.9), (-90, 0), (90, 0), (50.85, 4.35)]
    )
    try:
        cities, km, _ = reference.nearest(coordinates)
        for i, (lat, lon) in enumerate(coordinates):
            identity, distance = oracle.nearest(lat, lon)
            row = int(
                np.flatnonzero(reference.pack.arrays["places"]["id"] == identity)[0]
            )
            expected = reference.city_ids[row] if distance <= 50 else 0
            assert cities[i] == expected
            assert km[i] == pytest.approx(distance, abs=1e-7)
    finally:
        reference.close()


@pytest.mark.parametrize(
    "point,city",
    [
        ((40.7128, -74.0060), "New York City"),
        ((35.6895, 139.6917), "Tokyo"),
        # GeoNames 1865090 is PPL, despite being inside Tokyo; no name exceptions.
        ((35.6762, 139.6503), "Asagaya-minami"),
    ],
)
def test_world_current_city_names(
    world: Geocoder, point: tuple[float, float], city: str
) -> None:
    location = world.reverse(*point)
    assert location is not None
    assert location.city == city

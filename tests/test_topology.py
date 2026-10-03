"""Build-only scalar and vector policy at overlaps, seams, holes and ties."""

import numpy as np
import pytest

from build_data.reference.oracle import Reference
from thereabouts.models import Location


@pytest.mark.parametrize(
    "point,expected",
    [
        ((1, 5), Location(None, "Left", "Alpha", "AA")),
        ((3.5, 3.5), Location(None, None, "Enclave", "BB")),
        ((1, 9.5), Location(None, "Right", "Alpha", "AA")),
        ((19.005, 19.005), Location(None, None, "Alpha", "AA")),
        ((5, 15), Location(None, None, None, None)),
        ((30, 30), None),
        ((1, 4), Location("Western", "Left", "Alpha", "AA")),
    ],
)
def test_reference_policy(
    synthetic: Reference, point: tuple[float, float], expected: Location | None
) -> None:
    assert synthetic.scalar(*point) == expected
    assert synthetic.locations(synthetic.labels(np.array([point])))[0] == expected


def test_nearest_cutoff_and_tie(synthetic: Reference) -> None:
    # Exact co-location selects ID 10, while the equidistant point is >50 km away.
    names, distance, _ = synthetic.nearest(np.array([[1, 4], [1, 5]], dtype=float))
    assert synthetic.cities[int(names[0])] == "Western"
    assert distance[0] == 0
    assert names[1] == 0


def test_admin1_only_coverage_does_not_create_a_row(synthetic: Reference) -> None:
    assert synthetic.admin.layers["admin1"].query(30, 30)
    assert not synthetic.admin.layers["country"].query(30, 30)
    assert not synthetic.admin.layers["land"].query(30, 30)
    assert synthetic.scalar(30, 30) is None
    assert synthetic.labels(np.array([[30.0, 30.0]])).tolist() == [0]

"""Coordinates tolerate last-bit platform differences; nothing else does."""

import pytest

from tests.client.conformance.compare import assert_same, difference


def test_coordinates_within_a_nanodegree_match() -> None:
    expected = {"point": {"lat": 50.847598515658675, "lon": 4.355497724254153}}
    assert_same(
        {"point": {"lat": 50.84759851565868, "lon": 4.35549772425415}}, expected
    )
    assert difference(
        {"point": {"lat": 50.8475985, "lon": 4.355497724254153}}, expected
    )


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        ({"distance_km": 1.0000000000001}, {"distance_km": 1.0}),
        ({"lat": "1.0"}, {"lat": 1.0}),
        ({"point": {"lat": 1.0}}, {"point": {"lat": 1.0, "lon": 2.0}}),
        ({"candidates": [1, 2]}, {"candidates": [1]}),
        ({"name": "Brussel"}, {"name": "Brussels"}),
    ],
)
def test_every_other_value_is_exact(actual: object, expected: object) -> None:
    with pytest.raises(AssertionError, match=r"\$"):
        assert_same(actual, expected, "case")

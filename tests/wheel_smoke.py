"""Run against an installed wheel, outside the source import path."""

import sys
from pathlib import Path

from h3.api import basic_int as h3

import thereabouts
from thereabouts.client import Geocoder


def check(pack: Path, expected_backend: str) -> None:
    assert Path(thereabouts.__file__).is_relative_to(Path(sys.prefix))
    root = h3.latlng_to_cell(12.97, 77.59, 3)
    cell = h3.int_to_str(h3.cell_to_center_child(h3.cell_to_children(root, 4)[0], 8))
    with (
        Geocoder(pack, verify=True) as geo,
        Geocoder(pack, backend="python") as reference,
    ):
        assert geo.info()["backend"] == expected_backend
        answer = geo.from_h3(cell)
        assert answer == reference.from_h3(cell)
        assert answer.selected is not None and answer.selected.city is not None
        assert answer.selected.city.id == "city:synthetic:A"
        assert list(geo.from_h3_many([cell])) == [answer]
    assert "pyarrow" not in sys.modules and "Cython" not in sys.modules


if __name__ == "__main__":
    check(Path(sys.argv[1]), sys.argv[2])

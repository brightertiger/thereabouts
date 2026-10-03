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
    assert not {"pyarrow", "Cython", "mcp", "pydantic"}.intersection(sys.modules)


def check_codes(fixtures: Path) -> None:
    with Geocoder(fixtures / "postal", verify=True) as geo:
        answer = geo.postal("00100", country="AA")
        assert answer.selected is not None
        assert len(answer.selected.observations) == 2
    with Geocoder(fixtures / "airports", verify=True) as geo:
        answer = geo.airport("ZZZ", scheme="iata")
        assert answer.status == "ambiguous" and answer.selected is None
        assert len(answer.candidates) == 2


if __name__ == "__main__":
    check(Path(sys.argv[1]), sys.argv[2])
    if len(sys.argv) > 3:
        check_codes(Path(sys.argv[3]))

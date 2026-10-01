"""Offline fixtures, including explicit synthetic topology and tie cases."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from shapely.geometry import Polygon, box

from build_data.pack import write_pack
from build_data.records import AdminRecord, Settlement
from build_data.reference.oracle import Reference
from pyofflinegeocoder import Geocoder

FIXTURE = Path(__file__).parent / "fixtures" / "benelux"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.network_guard import install

    install(monkeypatch)


@pytest.fixture
def geocoder() -> Iterator[Geocoder]:
    with Geocoder(FIXTURE) as geocoder:
        yield geocoder


@pytest.fixture(scope="session")
def synthetic_pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("synthetic") / "pack"
    shell = Polygon(
        box(0, 0, 10, 10).exterior.coords, [box(3, 3, 4, 4).exterior.coords]
    )
    countries = [
        AdminRecord("test:A", "Alpha", "AA", -1, 2, [shell, box(19, 19, 19.01, 19.01)]),
        AdminRecord("test:B", "Enclave", "BB", -1, 0, [box(3, 3, 4, 4)]),
        AdminRecord("test:C", "Overlap", "CC", -1, 0, [box(9, 0, 11, 2)]),
        AdminRecord("test:D", "No subdivisions", "DD", -1, 1, [box(12, 0, 14, 2)]),
        AdminRecord("test:E", "Missing subdivisions", "", -1, 0, [box(15, 0, 17, 2)]),
    ]
    subdivisions = [
        AdminRecord("test:L", "Left", "AA-L", 0, 0, [box(0, 0, 5, 3)]),
        AdminRecord("test:R", "Right", "AA-R", 0, 0, [box(5, 0, 10, 3)]),
        AdminRecord("test:O", "Marine spill", "", -1, 0, [box(29, 29, 31, 31)]),
    ]
    places = [
        Settlement(10, "Western", "PPL", 1, 4, "ZZ", "99"),
        Settlement(20, "Eastern", "PPL", 1, 6, "AA", "R"),
        Settlement(30, "Co-located", "PPL", 1, 4, "AA", "L"),
    ]
    write_pack(
        path,
        countries,
        subdivisions,
        [box(0, 0, 18, 18)],
        places,
        None,
        [],
        snapshot_id="synthetic-tests",
    )
    return path


@pytest.fixture
def synthetic(synthetic_pack: Path) -> Iterator[Reference]:
    reference = Reference(synthetic_pack)
    yield reference
    reference.close()


@pytest.fixture(scope="session")
def world_path() -> Path:
    value = os.environ.get("PYOFFLINEGEOCODER_WORLD_DATA")
    if not value or not (Path(value) / "manifest.json").is_file():
        pytest.skip("set PYOFFLINEGEOCODER_WORLD_DATA to a built world pack")
    return Path(value)


@pytest.fixture(scope="session")
def world(world_path: Path) -> Iterator[Geocoder]:
    with Geocoder(world_path) as geocoder:
        yield geocoder

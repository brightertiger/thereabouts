"""Thin boundary tests: lifecycle, discovery, immutable results and columns."""

import json
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import thereabouts
from thereabouts import (
    ClosedGeocoderError,
    CorruptPackError,
    DataNotInstalledError,
    Geocoder,
    IncompatibleDataError,
    _core,
)
from thereabouts.packs.jsonio import sha256
from thereabouts.store import core_pack

FIXTURES = Path(__file__).parents[1] / "fixtures"
SAMPLE = FIXTURES / "packs/core-sample"


@pytest.mark.parametrize(
    "bundle", ["core-sample-vectors.json", "core-synthetic-vectors.json"]
)
def test_shared_vectors(bundle: str) -> None:
    value = json.loads((FIXTURES / bundle).read_text())
    with Geocoder(FIXTURES / value["pack"]) as geo:
        for case in value["cases"]:
            request = case["request"]
            values = request["values"]
            result = (
                geo.from_h3(values[0])
                if request["kind"] == "h3"
                else geo.reverse(lat=values[0], lon=values[1])
            )
            assert result.to_dict() == case["result"], case["id"]


def test_public_exports_and_keyword_coordinates() -> None:
    assert set(thereabouts.__all__) == {
        "Geocoder",
        "reverse",
        "Result",
        "GeocoderError",
        "DataNotInstalledError",
        "IncompatibleDataError",
        "CorruptPackError",
        "ClosedGeocoderError",
    }
    with Geocoder(SAMPLE) as geo:
        with pytest.raises(TypeError):
            geo.reverse(50.85, 4.35)  # type: ignore[misc]
        result = geo.reverse(lat=50.8503, lon=4.3517)
        assert result.country is not None and result.country.code == "BE"
        assert result.country.code3 == "BEL"
        assert result.timezone == "Europe/Brussels"
        assert result.city is not None and result.city.point is not None
        with pytest.raises(FrozenInstanceError):
            result.status = "changed"  # type: ignore[misc]
        assert "evidence" not in result.to_dict()
        evidence = geo.reverse(lat=50.8503, lon=4.3517, evidence=True)
        assert evidence.evidence is not None
        assert evidence.evidence.stored_cell is not None
        assert evidence.to_dict()["evidence"]["source_ids"]


def test_closed_and_batch_lifecycle() -> None:
    geo = Geocoder(SAMPLE)
    results = geo.reverse_many([(50.85, 4.35), (52.36, 4.9)])
    next(results)
    geo.close()
    geo.close()
    operations: list[Callable[[], object]] = [
        lambda: next(results),
        lambda: geo.from_h3("881fa445b3fffff"),
        lambda: geo.__enter__(),
    ]
    for operation in operations:
        with pytest.raises(ClosedGeocoderError) as caught:
            operation()
        assert caught.value.code == "closed_geocoder"


@pytest.mark.parametrize(
    "lat,lon",
    [
        (True, 0),
        (None, 0),
        ("0", 0),
        (float("nan"), 0),
        (0, float("inf")),
        (91, 0),
        (0, 181),
    ],
)
def test_invalid_scalar(lat: Any, lon: Any) -> None:
    with Geocoder(SAMPLE) as geo:
        assert geo.reverse(lat=lat, lon=lon).status == "invalid_input"


def test_columns_strides_null_masks_and_order() -> None:
    lat = np.array([50.8503, 0, 52.3676, 0, 49.6116, 0, float("nan"), 0])[::2]
    lon = np.array([4.3517, 0, 4.9041, 0, 6.1319, 0, 0, 0])[::2]
    with Geocoder(SAMPLE) as geo:
        columns = geo.reverse_columns(lat, lon)
        results = list(geo.reverse_many(zip(lat, lon, strict=True)))
        assert list(columns["status"]) == [r.status for r in results]
        assert list(columns["country_code"]) == [
            r.country.code if r.country else None for r in results
        ]
        assert not columns["point_lat_valid"][-1]
        assert not columns["distance_band_at_most_km_valid"].any()
        assert columns["city_population"].dtype == np.uint32
        assert all(len(value) == 4 for value in columns.values())
        assert all(
            len(value) == 0
            for value in geo.reverse_columns(np.array([]), np.array([])).values()
        )
        with pytest.raises(ValueError):
            geo.reverse_columns(lat, lon[:1])
        with pytest.raises(ValueError):
            geo.reverse_columns(lat.reshape(2, 2), lon)
        with pytest.raises(TypeError):
            geo.reverse_columns(np.array([True]), np.array([0.0]))


def test_parallel_native_batches() -> None:
    with Geocoder(SAMPLE) as geo, ThreadPoolExecutor(max_workers=2) as pool:
        lat, lon = np.full(1000, 50.85), np.full(1000, 4.35)
        tasks = [pool.submit(geo.reverse_columns, lat, lon) for _ in range(2)]
        for task in tasks:
            assert all(task.result()["country_code"] == "BE")


def test_discovery_exact_command_and_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("THEREABOUTS_DATA", str(tmp_path))
    with pytest.raises(
        DataNotInstalledError, match=r"^thereabouts data install core$"
    ) as caught:
        Geocoder()
    assert caught.value.code == "data_not_installed"
    digest = sha256(SAMPLE / "manifest.json")
    destination = tmp_path / "packs/core/v-2026.10" / digest
    shutil.copytree(SAMPLE, destination)
    pointer = tmp_path / "packs/core/current.json"
    pointer.write_text(
        json.dumps(
            dict(
                path=destination.relative_to(tmp_path).as_posix(),
                manifest_sha256=digest,
            )
        )
    )
    assert core_pack() == destination
    with Geocoder() as geo:
        assert geo.reverse(lat=50.85, lon=4.35).status == "matched"
    data_file = next(destination.glob("cells-*.bin"))
    content = bytearray(data_file.read_bytes())
    content[-1] ^= 1
    data_file.write_bytes(content)
    with pytest.raises(CorruptPackError) as corrupt:
        _core.open(str(destination), verify=True)
    assert corrupt.value.code == "corrupt_pack"


def test_old_installation_is_discovered_and_rejected(tmp_path: Path) -> None:
    from thereabouts.installing.install import install

    source = FIXTURES / "serving"
    install(
        str(source), data_dir=tmp_path, manifest_sha256=sha256(source / "manifest.json")
    )
    with pytest.raises(IncompatibleDataError) as caught:
        Geocoder(data_dir=tmp_path)
    assert caught.value.code == "incompatible_data"


def test_native_pack_helpers() -> None:
    assert _core.pack_info(str(SAMPLE))["format_version"] == 2
    assert _core.verify_pack(str(SAMPLE))["family"] == "core"


def test_distant_evidence() -> None:
    cases = json.loads((FIXTURES / "core-sample-vectors.json").read_text())["cases"]
    with Geocoder(SAMPLE) as geo:
        case = next(
            c
            for c in cases
            if c["request"]["kind"] == "h3"
            and c["result"]["match"] == "nearest_distant"
        )
        result = geo.from_h3(case["request"]["values"][0], evidence=True)
        assert result.status == "matched" and result.candidates == ()
        assert result.distance_band is not None and result.evidence is not None
        assert result.distance_band.greater_than_km == 25
        assert result.distance_band.at_most_km == 50
        assert "selected" not in result.to_dict()
        assert "distance_km" not in result.to_dict()


def test_lazy_shortcut_and_closed_native_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from thereabouts import geocoder

    with Geocoder(SAMPLE) as geo:
        monkeypatch.setattr(geocoder, "_default", geo)
        assert thereabouts.reverse(lat=50.85, lon=4.35).status == "matched"
    native = _core.open(str(SAMPLE))
    native.close()
    with pytest.raises(ClosedGeocoderError):
        native.reverse(50.85, 4.35)

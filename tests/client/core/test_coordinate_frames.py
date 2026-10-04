"""Coordinate binding contracts; native integration uses the core-owned vectors."""

import inspect
import json
from collections.abc import Iterator
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from thereabouts import ClosedGeocoderError, Geocoder, _core
from thereabouts.coords import Point, QueryMetadata, _point_json
from thereabouts.results import Point as ResultPoint
from thereabouts.results import Result

FIXTURES = Path(__file__).parents[2] / "fixtures"
SAMPLE = FIXTURES / "packs/core-sample"
INVALID = {"__thereabouts_invalid_number__": True}


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), True, np.bool_(False)]
)
@pytest.mark.parametrize(
    "field", ["height", "geoid_separation", "accuracy_m", "hdop", "vdop"]
)
def test_adapter_optional_invalid_numbers_are_not_erased(
    value: Any, field: str
) -> None:
    point: dict[str, Any] = {"lat": 0, "lon": 0}
    if field in ("height", "geoid_separation"):
        point[field] = value
        assert json.loads(_point_json(point))[field] == INVALID
    else:
        point["uncertainty"] = {field: value}
        assert json.loads(_point_json(point))["uncertainty"][field] == INVALID


def test_adapter_numpy_scalars_and_integer_ids_are_lossless() -> None:
    assert json.loads(_point_json({"lat": np.float32(1), "lon": np.int32(2)})) == {
        "lat": 1,
        "lon": 2,
    }
    value = (1 << 63) + 1
    assert (
        json.loads(_point_json({"frame": "s2", "cell": np.uint64(value)}))["cell"]
        == value
    )
    assert json.loads(_point_json({"height": 10**5000}))["height"] == INVALID
    with pytest.raises(TypeError):
        _point_json((1, 2, 3))
    with pytest.raises(TypeError):
        _point_json({1: 0})


def test_adapter_metadata_is_deeply_frozen_and_roundtrips() -> None:
    query = {
        "input_frame": "enu",
        "declared_frame": "enu",
        "normalized": {
            "lat": 0.0,
            "lon": 0.0,
            "height": 0.0,
            "height_datum": "ellipsoid",
            "geoid_separation": None,
        },
        "origin": {
            "frame": "geodetic",
            "lat": 0.0,
            "lon": 0.0,
            "height": None,
            "height_datum": None,
            "geoid_separation": None,
        },
        "conversion": ["origin_height_assumed_zero"],
        "source_height": None,
        "uncertainty": {"accuracy_m": 4.0, "hdop": 0.9, "vdop": None},
        "cell_extent": {
            "boundary": [{"lat": 0.0, "lon": 0.0}],
            "half_lat_deg": None,
            "half_lon_deg": None,
            "grid_size_m": None,
            "radius_m": 0.0,
        },
        "nmea": None,
        "error": None,
    }
    value = QueryMetadata.from_dict(query)
    assert value.to_dict() == query
    assert (
        value.normalized is not None
        and value.origin is not None
        and value.cell_extent is not None
    )
    for target, name in [
        (value, "input_frame"),
        (value.normalized, "lat"),
        (value.origin, "lat"),
        (value.uncertainty, "hdop"),
        (value.cell_extent.boundary[0], "lat"),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(target, name, "changed")
    assert isinstance(value.conversion, tuple)
    assert isinstance(value.cell_extent.boundary, tuple)
    old = json.loads((FIXTURES / "core-sample-vectors.json").read_text())["cases"][0][
        "result"
    ]
    assert Result.from_dict(old).to_dict() == old
    assert Result.from_dict(old).query is None
    new = {**old, "query": query}
    assert Result.from_dict(new).to_dict() == new
    assert ResultPoint(1, 2) == ResultPoint(lat=1, lon=2)


def test_scalar_provenance_and_old_signatures() -> None:
    with Geocoder(SAMPLE) as geo:
        point: Point = {
            "lat": 48.8566,
            "lon": 2.3522,
            "uncertainty": {"accuracy_m": 4, "hdop": 0.9, "vdop": 1.2},
        }
        result = geo.reverse_point(point)
        old = geo.reverse(lat=48.8566, lon=2.3522)
        new = result.to_dict()
        query = new.pop("query")
        assert new == old.to_dict()
        assert query["declared_frame"] is None
        assert query["normalized"]["lat"] == 48.8566
        assert query["uncertainty"] == {"accuracy_m": 4, "hdop": 0.9, "vdop": 1.2}
        assert result.point != ResultPoint(48.8566, 2.3522)
        assert result.evidence is None
        assert geo.reverse_point(point, evidence=True).evidence is not None
        assert (
            inspect.signature(Geocoder.reverse).parameters["lat"].kind
            is inspect.Parameter.KEYWORD_ONLY
        )
        native = geo._handles.get("core")
        for method in (native.reverse, native.from_h3, native.reverse_point):
            assert (
                inspect.signature(method).parameters["evidence"].kind
                is inspect.Parameter.KEYWORD_ONLY
            )
        with pytest.raises(TypeError):
            native.reverse_point("{}", True)  # type: ignore[misc]
        assert native.reverse_point("{")["query"]["error"]["code"] == "invalid_syntax"


@pytest.mark.parametrize(
    "value", [True, np.bool_(False), "1", float("nan"), float("inf"), -float("inf")]
)
@pytest.mark.parametrize(
    "field", ["height", "geoid_separation", "accuracy_m", "hdop", "vdop"]
)
def test_native_optional_numeric_failures(value: Any, field: str) -> None:
    point: dict[str, Any] = {"lat": 0, "lon": 0}
    if field in ("height", "geoid_separation"):
        point[field] = value
    else:
        point["uncertainty"] = {field: value}
    with Geocoder(SAMPLE) as geo:
        result = geo.reverse_point(cast(Point, point))
        assert result.status == "invalid_input"
        assert result.query is not None and result.query.error is not None
        assert result.query.error.code == "invalid_type"
        assert result.query.normalized is None


@pytest.mark.parametrize(
    ("point", "code", "message"),
    [
        (
            {"frame": "enu", "e": 0, "n": 0, "u": 0},
            "missing_origin",
            "Frame enu/ned requires an explicit geodetic or ECEF origin",
        ),
        (
            {"frame": "pluscode", "value": "CWC8+R9"},
            "missing_reference",
            "Short plus codes require a geodetic reference; use a full plus code "
            "otherwise",
        ),
        (
            {"frame": "llv"},
            "unsupported_frame",
            "Choose frame enu or ned and supply an origin; llv does not define "
            "axis order",
        ),
        (
            {"frame": "crs:EPSG:3857", "x": 0, "y": 0},
            "unsupported_frame",
            "Thereabouts does not transform arbitrary CRSs; use GeoReconcile crs: "
            "support or pyproj, then pass WGS84 geodetic coordinates",
        ),
        (
            {"frame": "ecef", "x": 0, "y": 0, "z": 0},
            "undefined_position",
            "ECEF position or local-frame orientation is undefined; provide a "
            "valid position and a geodetic pole origin",
        ),
        (
            {"lat": 91, "lon": 0},
            "out_of_range",
            "Coordinate field lat is outside the supported range",
        ),
        (
            {
                "frame": "enu",
                "e": 0,
                "n": 0,
                "u": 0,
                "origin": {"lat": 0, "lon": 0, "height": 5, "height_datum": "msl"},
            },
            "missing_ellipsoidal_height",
            "ECEF conversion requires ellipsoidal height or a supplied geoid "
            "separation; no geoid model is applied",
        ),
        (
            {"frame": "h3", "cell": "891fb466257ffff"},
            "unsupported_cell_resolution",
            "H3 reverse queries support resolutions 0 through 8; use an explicit "
            "parent cell",
        ),
        (
            {
                "frame": "nmea",
                "value": (
                    "$GPRMC,123519,V,4807.038,N,01131.000,E,"
                    "022.4,084.4,230394,003.1,W*7D"
                ),
            },
            "no_fix",
            "NMEA sentence does not contain an active position fix",
        ),
        (
            {"frame": "nmea", "value": "$GPGGA,broken*00"},
            "invalid_checksum",
            "NMEA checksum is missing or invalid",
        ),
    ],
)
def test_diagnostics(point: Any, code: str, message: str) -> None:
    with Geocoder(SAMPLE) as geo:
        result = geo.reverse_point(point)
        assert result.status == "invalid_input"
        assert result.query is not None and result.query.error is not None
        assert result.query.error.code == code
        assert result.hint == message == result.query.error.message


def test_heights_aliases_and_h3_keep_their_semantics() -> None:
    with Geocoder(SAMPLE) as geo:
        for alias in ("geodetic", "latlon", "lla", "llh"):
            result = geo.reverse_point(
                cast(
                    Point,
                    {
                        "frame": alias,
                        "lat": 0,
                        "lon": 0,
                        "height": 20,
                        "height_datum": "msl",
                    },
                )
            )
            assert result.query is not None and result.query.normalized is not None
            assert result.query.input_frame == "geodetic"
            assert result.query.declared_frame == alias
            assert result.query.normalized.height is None
            assert result.query.source_height is not None
            assert result.query.source_height.value_m == 20
        for cell in ("801ffffffffffff", "881fb46625fffff"):
            value = geo.reverse_point({"frame": "h3", "cell": cell}).to_dict()
            query = value.pop("query")
            assert value == geo.from_h3(cell).to_dict()
            assert query["cell_extent"] is not None
            assert geo.reverse_point(
                {"frame": "h3", "cell": int(cell, 16)}
            ).to_dict() == {**value, "query": query}


def test_numeric_columns_strides_masks_empty_and_domain_errors() -> None:
    lat = np.array([48.8566, 99, 50.85, 99, np.nan, 99])[::2]
    lon = np.array([2.3522, 99, 4.35, 99, 0, 99])[::2]
    with Geocoder(SAMPLE) as geo:
        result = geo.reverse_frame_columns(
            {"lat": lat, "lon": lon, "hdop": np.array([0.9, 1, np.inf])}
        )
        assert result["query"].dtype == object
        assert len(result["query"]) == 3
        assert all(isinstance(q, QueryMetadata) for q in result["query"])
        assert result["query"][0].uncertainty.hdop == 0.9
        assert result["query"][2].error.code == "non_finite"
        assert result["point_lat_valid"].tolist() == [True, True, False]
        old = geo.reverse_columns(lat, lon)
        for key in old:
            if key not in ("hint", "hint_categories"):
                np.testing.assert_equal(result[key], old[key])
        assert "query" not in old
        invalid_lat = geo.reverse_frame_columns(
            {"lat": np.array([np.nan]), "lon": np.array([0.0])}
        )
        assert (
            invalid_lat["query"][0].error.message
            == "Coordinate field lat must be finite"
        )
        empty = geo.reverse_frame_columns({"lat": np.array([]), "lon": np.array([])})
        assert all(len(values) == 0 for values in empty.values())
        native = geo._handles.get("core")
        with pytest.raises(TypeError):
            native.reverse_frame_columns(
                {"lat": np.array([True]), "lon": np.array([0.0])}
            )
        native_int = native.reverse_frame_columns(
            {"lat": np.array([0]), "lon": np.array([0])}
        )
        assert len(native_int["query"]) == 1
        for columns, error in [
            ({"lat": lat, "lon": lon[:1]}, ValueError),
            ({"lat": np.zeros((1, 1)), "lon": lon}, ValueError),
            ({"lat": np.array([True]), "lon": lon}, TypeError),
            ({"lat": lat}, ValueError),
            ({"lat": lat, "lon": lon, "extra": lat}, ValueError),
        ]:
            with pytest.raises(error):
                geo.reverse_frame_columns(columns)
        with pytest.raises(ValueError, match="reverse_points"):
            geo.reverse_frame_columns({"lat": lat, "lon": lon}, frame="utm")


@pytest.mark.parametrize(
    ("frame", "columns"),
    [
        ("ecef", {"x": [6378137.0], "y": [0.0], "z": [0.0]}),
        ("enu", {"e": [10.0], "n": [0.0], "u": [0.0]}),
        ("ned", {"n": [0.0], "e": [10.0], "d": [0.0]}),
    ],
)
def test_numeric_frame_columns_match_scalar(
    frame: Any, columns: dict[str, list[float]]
) -> None:
    origin: Any = None if frame == "ecef" else {"lat": 48.8566, "lon": 2.3522}
    request = {"frame": frame, **{key: value[0] for key, value in columns.items()}}
    if origin is not None:
        request["origin"] = origin
    with Geocoder(SAMPLE) as geo:
        result = geo.reverse_frame_columns(
            {key: np.array(value) for key, value in columns.items()},
            frame=frame,
            origin=origin,
        )
        scalar = geo.reverse_point(cast(Point, request))
        assert result["query"][0] == scalar.query


def test_stream_order_backpressure_and_close() -> None:
    seen: list[int] = []

    def points() -> Iterator[Point]:
        for i in range(3):
            seen.append(i)
            yield {"lat": i, "lon": 0}

    geo = Geocoder(SAMPLE)
    stream = geo.reverse_points(points())
    assert seen == []
    first = next(stream)
    assert seen == [0]
    assert first.query is not None and first.query.normalized is not None
    assert first.query.normalized.lat == 0
    geo.close()
    with pytest.raises(ClosedGeocoderError):
        next(stream)
    assert seen == [0]
    with Geocoder(SAMPLE) as other:
        ordered = list(
            other.reverse_points(
                [{"lat": 2, "lon": 0}, {"lat": 91, "lon": 0}, {"lat": 1, "lon": 0}]
            )
        )
        assert [result.status for result in ordered][1] == "invalid_input"
        assert [
            result.query.normalized.lat
            for result in (ordered[0], ordered[2])
            if result.query is not None and result.query.normalized is not None
        ] == [2, 1]
        one = other.reverse_points([{"lat": 0, "lon": 0}])
        next(one)
        other.close()
        with pytest.raises(ClosedGeocoderError):
            next(one)
    with Geocoder(SAMPLE) as other, pytest.raises(TypeError):
        other.reverse_point(cast(Point, (1, 2, 3)))
    native = _core.open(str(SAMPLE))
    native.close()
    with pytest.raises(ClosedGeocoderError):
        native.reverse_point("{")


def _assert_vector(
    actual: Any, expected: Any, tolerances: dict[str, float], path: str = ""
) -> None:
    if isinstance(expected, dict):
        for key, value in expected.items():
            _assert_vector(actual[key], value, tolerances, f"{path}.{key}".lstrip("."))
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for a, e in zip(actual, expected, strict=True):
            _assert_vector(a, e, tolerances, f"{path}.*")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        # Same angular comparison as the core fixture runner, including ±180.
        delta = actual - expected
        if path.endswith(".lon"):
            delta = (delta + 180) % 360 - 180
        assert abs(delta) <= tolerances.get(path, 0), path
    else:
        assert actual == expected, path


def test_shared_coordinate_vectors_native_schema_and_lookup() -> None:
    # Missing core-owned fixtures deliberately fail this integration gate.
    vectors = json.loads((FIXTURES / "coordinates/vectors.json").read_text())
    assert vectors["schema_version"] == 1
    frames: set[str] = set()
    with Geocoder(SAMPLE) as geo:
        native = geo._handles.get("core")
        for case in vectors["cases"]:
            point = case["input"]
            frames.add(point.get("frame", "geodetic"))
            result = geo.reverse_point(point).to_dict()
            assert result == native.reverse_point(json.dumps(point)), case["id"]
            query = result.pop("query")
            assert set(query) == {
                "input_frame",
                "declared_frame",
                "normalized",
                "origin",
                "conversion",
                "source_height",
                "uncertainty",
                "cell_extent",
                "nmea",
                "error",
            }
            assert set(query["uncertainty"]) == {"accuracy_m", "hdop", "vdop"}
            expected = case["expected"]
            if "error" in expected:
                assert result["status"] == "invalid_input", case["id"]
                assert query["error"]["code"] == expected["error"], case["id"]
                assert result["hint"] == query["error"]["message"]
                assert query["normalized"] is None
            else:
                assert query["error"] is None, case["id"]
                _assert_vector(query, expected, case["tolerance"])
                normalized = query["normalized"]
                assert set(normalized) == {
                    "lat",
                    "lon",
                    "height",
                    "height_datum",
                    "geoid_separation",
                }
                if point.get("frame") == "h3":
                    cell = point["cell"]
                    legacy = geo.from_h3(
                        cell if isinstance(cell, str) else format(cell, "x")
                    )
                else:
                    legacy = geo.reverse(lat=normalized["lat"], lon=normalized["lon"])
                assert result == legacy.to_dict(), case["id"]
    assert {
        "geodetic",
        "ecef",
        "enu",
        "ned",
        "utm",
        "mgrs",
        "geohash",
        "pluscode",
        "h3",
        "s2",
        "dms",
        "nmea",
        "geojson",
        "wkt",
    } <= frames

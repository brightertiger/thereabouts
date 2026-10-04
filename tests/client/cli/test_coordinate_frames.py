"""The Python console stays a shim over the shared native coordinate CLI."""

import csv
import io
import json
from pathlib import Path
from typing import cast

import pytest

from thereabouts import Geocoder
from thereabouts.coords import Point

from .helpers import FIXTURES, console, install_fixture


@pytest.fixture
def store(tmp_path: Path) -> Path:
    install_fixture(tmp_path, FIXTURES / "packs/core-sample")
    return tmp_path


def test_scalar_point_metadata_and_selected_fields(store: Path) -> None:
    fixture = json.loads((FIXTURES / "coordinates/vectors.json").read_text())
    case = next(c for c in fixture["cases"] if c["id"] == "msl_with_separation")
    point = {
        **case["input"],
        "frame": "llh",
        "uncertainty": {"accuracy_m": 4, "hdop": 1.2},
    }
    result = console(store, "reverse", "--point", json.dumps(point))
    assert result.returncode == 0, result.stderr
    answer = json.loads(result.stdout)
    assert answer["query"]["declared_frame"] == "llh"
    assert (
        answer["query"]["normalized"]["height"]
        == case["expected"]["normalized"]["height"]
    )
    assert answer["query"]["uncertainty"] == {
        "accuracy_m": 4,
        "hdop": 1.2,
        "vdop": None,
    }
    assert "evidence" not in answer
    assert list(answer)[-1] == "query"
    selected = console(
        store,
        "reverse",
        "--point",
        json.dumps(point),
        "--fields",
        "query.input_frame,query.normalized.height,query.uncertainty.hdop",
        "--csv",
    )
    assert selected.returncode == 0, selected.stderr
    assert next(csv.reader(io.StringIO(selected.stdout))) == [
        "query.input_frame",
        "query.normalized.height",
        "query.uncertainty.hdop",
    ]


@pytest.mark.parametrize(
    "flags",
    [
        ["--frame", "ecef", "--x", "1", "--y", "2"],
        ["--x", "1", "--y", "2", "--z", "3"],
        ["--lat", "0", "--lon", "0", "--height", "1"],
        ["--frame", "enu", "--x", "0", "--y", "0", "--z", "0"],
        ["--point", "{"],
        ["--point", "{}"],
        ["--point", '{"frame":"geodetic"}', "--frame", "geodetic"],
        ["-", "--point", '{"frame":"ecef"}'],
        ["--frame", "crs:EPSG:3857"],
        ["-", "--input-format", "nmea"],
        ["-", "--frame-col", "frame"],
    ],
)
def test_syntax_errors_do_not_open_data(tmp_path: Path, flags: list[str]) -> None:
    result = console(tmp_path / "absent", "reverse", *flags)
    assert result.returncode == 2
    assert not result.stdout
    assert "not installed" not in result.stderr


def test_csv_and_mixed_ndjson_keep_raw_columns_and_later_query(store: Path) -> None:
    raw = 'id,X,Z,Y,note\nbad,no,0,0,wrong\nok,6378137,0,0,"two\nlines"\n'
    result = console(
        store,
        "reverse",
        "-",
        "--frame",
        "ecef",
        "--x-col",
        "X",
        "--y-col",
        "Y",
        "--z-col",
        "Z",
        "--csv",
        stdin=raw,
    )
    assert result.returncode == 5, result.stderr
    reader = csv.DictReader(io.StringIO(result.stdout))
    records = list(reader)
    assert reader.fieldnames is not None
    assert reader.fieldnames[:5] == ["id", "X", "Z", "Y", "note"]
    assert reader.fieldnames[-1] == "thereabouts_query"
    assert records[0]["thereabouts_status"] == "invalid_input"
    assert records[1]["note"] == "two\nlines"
    assert json.loads(records[1]["thereabouts_query"])["input_frame"] == "ecef"
    result = console(
        store,
        "reverse",
        "-",
        "--input-format",
        "ndjson",
        "--csv",
        stdin='bad\n{"lat":0,"lon":0}\n{"frame":"geodetic","lat":0,"lon":0}\n',
    )
    assert result.returncode == 5, result.stderr
    records = list(csv.DictReader(io.StringIO(result.stdout)))
    assert records[0]["thereabouts_query"] == records[1]["thereabouts_query"] == ""
    assert json.loads(records[2]["thereabouts_query"])["input_frame"] == "geodetic"


def test_nmea_log_checks_every_nonblank_line(store: Path) -> None:
    sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    result = console(
        store,
        "reverse",
        "-",
        "--frame",
        "nmea",
        "--input-format",
        "nmea",
        stdin=f"\n{sentence}\n\n$GPGGA,bad*00\n",
    )
    assert result.returncode == 5, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 2
    assert rows[0]["value"] == sentence
    assert rows[0]["thereabouts_query"]["uncertainty"]["hdop"] == 0.9
    assert rows[1]["thereabouts_query"]["error"]["code"] == "invalid_checksum"


def test_console_help_fields_and_legacy_shape(tmp_path: Path, store: Path) -> None:
    for args in [("reverse", "--help"), ("--fields",)]:
        result = console(tmp_path / "absent", *args)
        assert result.returncode == 0, result.stderr
        assert (
            "--input-format" in result.stdout or "query.normalized.lat" in result.stdout
        )
    result = console(store, "reverse", "--lat", "48.8566", "--lon", "2.3522")
    assert result.returncode == 0, result.stderr
    assert "query" not in json.loads(result.stdout)


def assert_metadata(
    actual: object,
    expected: object,
    tolerance: dict[str, float],
    path: str = "",
    *,
    exact_schema: bool = False,
) -> None:
    """Read core-owned path tolerances; do not duplicate conversion maths."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        if exact_schema:
            assert actual.keys() == expected.keys(), path
        for key, value in expected.items():
            assert key in actual, path
            assert_metadata(
                actual[key],
                value,
                tolerance,
                f"{path}.{key}".lstrip("."),
                exact_schema=exact_schema,
            )
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        for left, right in zip(actual, expected, strict=True):
            assert_metadata(
                left, right, tolerance, f"{path}.*", exact_schema=exact_schema
            )
    elif isinstance(expected, (float, int)) and not isinstance(expected, bool):
        assert isinstance(actual, (float, int))
        delta = abs(actual - expected)
        if path.endswith(".lon"):
            delta = min(delta, abs(360 - delta))
        assert delta <= tolerance.get(path, 0), path
    else:
        assert actual == expected, path


def test_shared_coordinate_fixtures_through_console(store: Path) -> None:
    vectors = json.loads((FIXTURES / "coordinates/vectors.json").read_text())
    assert vectors["schema_version"] == 1
    with Geocoder(data_dir=store) as geo:
        for case in vectors["cases"]:
            point = {"frame": "geodetic", **case["input"]}
            result = console(store, "reverse", "--point", json.dumps(point))
            expected_error = case["expected"].get("error")
            assert result.returncode == (2 if expected_error else 0), (
                case["id"],
                result.stderr,
            )
            answer = json.loads(result.stdout)
            direct = geo.reverse_point(cast(Point, point)).to_dict()
            assert answer["status"] == direct["status"], case["id"]
            assert_metadata(
                answer["query"], direct["query"], case["tolerance"], exact_schema=True
            )
            if expected_error:
                assert answer["status"] == "invalid_input"
                assert answer["query"]["error"]["code"] == expected_error, case["id"]
            else:
                assert_metadata(answer["query"], case["expected"], case["tolerance"])


def test_raw_csv_frame_column_is_not_a_declaration(store: Path) -> None:
    result = console(
        store,
        "reverse",
        "-",
        "--frame",
        "ecef",
        stdin="frame,x,y,z\ngeodetic,NaN,0,0\n",
    )
    assert result.returncode == 5, result.stderr
    row = json.loads(result.stdout)
    assert row["frame"] == "geodetic"
    assert row["thereabouts_query"]["declared_frame"] == "ecef"

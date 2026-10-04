"""Strict MCP transport errors remain distinct from coordinate-domain results."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from pydantic import TypeAdapter, ValidationError

from thereabouts import Geocoder
from thereabouts.mcp_service.coords import Point
from thereabouts.mcp_service.server import create_server

SAMPLE = Path(__file__).parents[2] / "fixtures/packs/core-sample"
ADAPTER: TypeAdapter[Point] = TypeAdapter(Point)


@pytest.mark.parametrize("value", [True, False, "1"])
@pytest.mark.parametrize(
    "field", ["height", "geoid_separation", "accuracy_m", "hdop", "vdop"]
)
def test_schema_rejects_numeric_coercion(value: Any, field: str) -> None:
    point: dict[str, Any] = {"frame": "geodetic", "lat": 0, "lon": 0}
    if field in ("height", "geoid_separation"):
        point[field] = value
    else:
        point["uncertainty"] = {field: value}
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(point)


@pytest.mark.parametrize(
    "point",
    [
        {"frame": "ecef", "x": True, "y": 0, "z": 0},
        {"frame": "geodetic", "lat": 0, "lon": 0, "x": 0},
        {
            "frame": "enu",
            "e": 0,
            "n": 0,
            "u": 0,
            "origin": {"frame": "ecef", "x": 1, "y": 0, "z": 0, "origin": {}},
        },
        {"frame": "h3", "cell": True},
        {"frame": "s2", "cell": 1.5},
        {"frame": "geojson", "coordinates": ["1", 2]},
        {"frame": "geojson", "coordinates": [1, 2, 3, 4]},
        {"frame": "geodetic", "lat": 0, "lon": 0, "uncertainty": {"sigma": 1}},
    ],
)
def test_schema_forbids_wrong_components(point: Any) -> None:
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(point)


def test_schema_discriminates_frames_origins_and_keeps_default_implicit() -> None:
    schema = ADAPTER.json_schema()
    assert schema["discriminator"]["propertyName"] == "frame"
    assert set(schema["discriminator"]["mapping"]) == {
        "geodetic",
        "latlon",
        "lla",
        "llh",
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
    }
    assert all(
        value["additionalProperties"] is False for value in schema["$defs"].values()
    )
    value = ADAPTER.validate_python({"lat": 91, "lon": 0})
    assert value.model_dump(exclude_unset=True) == {"lat": 91, "lon": 0}
    # Range/finite checks belong to Rust, including optional-field failures.
    assert ADAPTER.validate_python(
        {"lat": 0, "lon": 0, "height": float("inf")}
    ).height == float("inf")  # type: ignore[union-attr]


def test_mcp_coordinate_json_inventory_and_errors() -> None:
    async def check(geo: Geocoder) -> None:
        async with Client(create_server(geo)) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            tool = tools["reverse_point"]
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint and tool.annotations.idempotent_hint
            assert (
                not tool.annotations.destructive_hint
                and not tool.annotations.open_world_hint
            )
            assert set(tool.input_schema["properties"]) == {"point", "evidence"}
            assert set(tools["reverse"].input_schema["properties"]) == {
                "lat",
                "lon",
                "evidence",
            }
            for point in (
                {"frame": "ecef", "x": 6378137, "y": 0, "z": 0},
                {"lat": 91, "lon": 0},
                {
                    "frame": "geodetic",
                    "lat": 48.8566,
                    "lon": 2.3522,
                    "uncertainty": {"accuracy_m": 4, "hdop": 0.9},
                },
            ):
                response = await client.call_tool("reverse_point", {"point": point})
                assert not response.is_error
                assert response.structured_content == geo.reverse_point(point).to_dict()  # type: ignore[arg-type]
            invalid = await client.call_tool(
                "reverse_point", {"point": {"lat": True, "lon": 0}}
            )
            assert invalid.is_error
            geo.close()
            closed = await client.call_tool(
                "reverse_point", {"point": {"lat": 0, "lon": 0}}
            )
            assert closed.is_error and "closed_geocoder" in str(closed.content)

    with Geocoder(SAMPLE) as geo:
        asyncio.run(check(geo))

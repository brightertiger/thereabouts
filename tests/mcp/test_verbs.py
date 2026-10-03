"""The public MCP verbs serialize exactly the current core result model."""

import asyncio
from pathlib import Path
from typing import Any

from mcp import Client

from thereabouts import Geocoder
from thereabouts.mcp_service.server import create_server

PACKS = Path(__file__).parents[1] / "fixtures/packs"


def test_every_verb_returns_the_public_json() -> None:
    paths = {
        name: PACKS / f"{name}-sample"
        for name in ("core", "postal", "airports", "locode", "phone", "ip", "plates")
    }
    with Geocoder(packs=paths) as geo:
        cases: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
            (
                "reverse",
                {"lat": 48.8566, "lon": 2.3522},
                geo.reverse(lat=48.8566, lon=2.3522).to_dict(),
            ),
            ("h3", {"cell": "bad"}, geo.from_h3("bad").to_dict()),
            (
                "geocode",
                {"text": "Paris", "country": "FR"},
                geo.geocode("Paris", country="FR").to_dict(),
            ),
            (
                "postal",
                {"code": "75001", "country": "FR"},
                geo.postal("75001", country="FR").to_dict(),
            ),
            ("airport", {"code": "CDG"}, geo.airport("CDG").to_dict()),
            (
                "locode",
                {"code": "ANR", "country": "BE"},
                geo.locode("ANR", country="BE").to_dict(),
            ),
            ("phone", {"number": "+3225551234"}, geo.phone("+3225551234").to_dict()),
            ("ip", {"address": "8.8.8.8"}, geo.ip("8.8.8.8").to_dict()),
            ("plate", {"text": "AB-123-CD"}, geo.plate("AB-123-CD").to_dict()),
        ]

        async def check() -> None:
            async with Client(create_server(geo)) as client:
                tools = (await client.list_tools()).tools
                assert {tool.name for tool in tools} == {c[0] for c in cases}
                for tool in tools:
                    assert tool.annotations is not None
                    assert tool.annotations.read_only_hint
                    assert not tool.annotations.open_world_hint
                    assert "path" not in tool.input_schema.get("properties", {})
                for verb, request, expected in cases:
                    result = await client.call_tool(verb, request)
                    assert not result.is_error
                    assert result.structured_content == expected
                evidence = await client.call_tool(
                    "reverse", {"lat": 48.8566, "lon": 2.3522, "evidence": True}
                )
                assert (
                    evidence.structured_content
                    == geo.reverse(lat=48.8566, lon=2.3522, evidence=True).to_dict()
                )
                assert (await client.call_tool("install", {})).is_error

        asyncio.run(check())


def test_closed_handle_error_has_stable_code() -> None:
    geo = Geocoder(PACKS / "core-sample")
    geo.close()

    async def check() -> None:
        async with Client(create_server(geo)) as client:
            result = await client.call_tool("reverse", {"lat": 0.0, "lon": 0.0})
            assert result.is_error
            assert "closed_geocoder" in str(result.content)

    asyncio.run(check())

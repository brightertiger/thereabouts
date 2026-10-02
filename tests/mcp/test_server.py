import asyncio
import json
from dataclasses import replace
from typing import Any

import pytest
from mcp import Client
from mcp.types import TextContent

from tests.conformance.generate import FIXTURES, OUTPUT
from thereabouts.client import Geocoder
from thereabouts.mcp_service.models import MAX_BATCH_POINTS, PAGE_SIZE
from thereabouts.mcp_service.responses import page
from thereabouts.mcp_service.server import create_server

CASES = json.loads(OUTPUT.read_bytes())["cases"]


def request(case: dict[str, Any]) -> dict[str, Any]:
    value = case["request"]
    kind, values = value["kind"], value["values"]
    if kind == "coordinates":
        return {"kind": kind, "latitude": values[0], "longitude": values[1]}
    if kind == "h3":
        return {"kind": kind, "cell": values[0]}
    return {
        "kind": kind,
        "value": values[0],
        **{key: value[key] for key in ("country", "scheme") if key in value},
    }


@pytest.mark.parametrize("fixture", ["serving", "codes/postal", "codes/airports"])
def test_shared_serialization(fixture: str) -> None:
    async def check(geo: Geocoder) -> None:
        async with Client(create_server(geo)) as client:
            for case in (item for item in CASES if item["pack"] == fixture):
                result = await client.call_tool("resolve", {"request": request(case)})
                if "error" in case:
                    assert result.is_error
                    continue
                assert not result.is_error
                value = result.structured_content
                assert value is not None and value["result"] == case["result"]
                assert value["total_candidates"] == len(case["result"]["candidates"])
                assert value["truncated"] is False and value["next_offset"] is None
                assert isinstance(result.content[0], TextContent)
                assert json.loads(result.content[0].text) == value
                explanation = await client.call_tool(
                    "explain", {"request": request(case)}
                )
                assert explanation.structured_content == {
                    "page": value,
                    "raw_evidence_installed": False,
                }

    with Geocoder(FIXTURES / fixture) as geo:
        asyncio.run(check(geo))


def test_tool_schema_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    with Geocoder(FIXTURES / "serving") as geo:
        calls = []
        original = geo.reverse_many

        def tracked(*args: Any, **kwargs: Any) -> Any:
            calls.append(True)
            return original(*args, **kwargs)

        monkeypatch.setattr(geo, "reverse_many", tracked)

        async def check() -> None:
            async with Client(create_server(geo)) as client:
                tools = (await client.list_tools()).tools
                assert {tool.name for tool in tools} == {
                    "reverse",
                    "reverse_many",
                    "resolve",
                    "info",
                    "explain",
                }
                for tool in tools:
                    assert tool.output_schema is not None
                    assert tool.annotations is not None
                    assert tool.annotations.read_only_hint is True
                    assert tool.annotations.open_world_hint is False
                    assert "path" not in tool.input_schema.get("properties", {})
                batch = next(tool for tool in tools if tool.name == "reverse_many")
                assert (
                    batch.input_schema["properties"]["points"]["maxItems"]
                    == MAX_BATCH_POINTS
                )
                result = await client.call_tool(
                    "reverse_many", {"points": [[0, 0]] * (MAX_BATCH_POINTS + 1)}
                )
                assert result.is_error and not calls
                bad = await client.call_tool(
                    "resolve",
                    {"request": {"kind": "h3", "cell": "bad", "path": "/elsewhere"}},
                )
                assert bad.is_error
                info = (await client.call_tool("info")).structured_content
                assert info is not None and info["packs"] == geo.info()["packs"]
                assert info["mcp_limits"] == {
                    "batch_points": MAX_BATCH_POINTS,
                    "candidates_per_page": PAGE_SIZE,
                    "batch_results_per_page": PAGE_SIZE,
                }

        asyncio.run(check())


def test_batch_order_collect_and_schema_failure() -> None:
    with Geocoder(FIXTURES / "serving") as geo:
        points = [(12.97, 77.59), (91, 0), (0, 180)]
        expected = [row.to_dict() for row in geo.reverse_many(points, errors="collect")]

        async def check() -> None:
            async with Client(create_server(geo)) as client:
                result = await client.call_tool(
                    "reverse_many", {"points": points, "errors": "collect"}
                )
                assert not result.is_error and result.structured_content is not None
                assert result.structured_content["results"] == expected
                assert result.structured_content["count"] == len(points)
                assert result.structured_content["truncated"] is False
                raised = await client.call_tool("reverse_many", {"points": points})
                assert raised.is_error
                malformed = await client.call_tool(
                    "reverse_many", {"points": [[True, 0]], "errors": "collect"}
                )
                assert malformed.is_error
                reverse = await client.call_tool(
                    "reverse", {"latitude": 12.97, "longitude": 77.59}
                )
                assert reverse.structured_content is not None
                assert reverse.structured_content["result"] == expected[0]

        asyncio.run(check())


def test_candidate_pages_do_not_choose_or_hide_ambiguity() -> None:
    with Geocoder(FIXTURES / "codes/airports") as geo:
        answer = geo.airport("ZZZ", scheme="iata")
        first, second = page(answer, 0, 1), page(answer, 1, 1)
        assert first.result["status"] == second.result["status"] == "ambiguous"
        assert first.result["selected"] is second.result["selected"] is None
        assert first.total_candidates == second.total_candidates == 2
        assert first.next_offset == 1 and second.next_offset is None
        assert first.truncated and second.truncated
        left, right = first.result["candidates"], second.result["candidates"]
        assert isinstance(left, list) and isinstance(right, list)
        assert left + right == answer.to_dict()["candidates"]
        candidates = tuple(replace(answer.candidates[0], id=str(i)) for i in range(25))
        larger = replace(answer, candidates=candidates)
        partial = page(larger, 0, PAGE_SIZE)
        assert partial.total_candidates == 25 and partial.next_offset == PAGE_SIZE
        assert page(answer, 99, 1).result["candidates"] == []

        async def check() -> None:
            async with Client(create_server(geo)) as client:
                request = {"kind": "airport", "value": "ZZZ", "scheme": "iata"}
                result = await client.call_tool(
                    "resolve", {"request": request, "limit": 1}
                )
                assert result.structured_content == first.model_dump(mode="json")
                for options in (
                    {"limit": PAGE_SIZE + 1},
                    {"offset": -1},
                    {"limit": True},
                ):
                    invalid = await client.call_tool(
                        "resolve", {"request": request, **options}
                    )
                    assert invalid.is_error

        asyncio.run(check())


def test_batch_pages_preserve_order_and_validate_the_entire_request() -> None:
    with Geocoder(FIXTURES / "serving") as geo:
        points = [(12.97, 77.59), (0, 180)] * 12
        expected = [row.to_dict() for row in geo.reverse_many(points)]

        async def check() -> None:
            async with Client(create_server(geo)) as client:
                rows = []
                for offset in (0, PAGE_SIZE):
                    result = await client.call_tool(
                        "reverse_many", {"points": points, "offset": offset}
                    )
                    value = result.structured_content
                    assert value is not None and not result.is_error
                    assert value["total_results"] == len(points) and value["truncated"]
                    rows.extend(value["results"])
                assert rows == expected
                empty = await client.call_tool("reverse_many", {"points": []})
                assert empty.structured_content is not None
                assert empty.structured_content["truncated"] is False
                assert empty.structured_content["results"] == []
                bad = await client.call_tool(
                    "reverse_many", {"points": [*points, (91, 0)]}
                )
                assert bad.is_error  # The invalid row is beyond the returned page.

        asyncio.run(check())

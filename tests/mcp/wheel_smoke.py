"""Qualify stdio from an installed wheel, with source imports excluded by -I."""

import asyncio
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

import thereabouts
from thereabouts.client import Geocoder


async def check(pack: Path) -> None:
    assert Path(thereabouts.__file__).is_relative_to(Path(sys.prefix))
    with Geocoder(pack) as geo:
        expected = geo.reverse(12.97, 77.59).to_dict()
    launch = StdioServerParameters(
        command=sys.executable,
        args=["-I", "-m", "thereabouts", "--pack", str(pack.resolve()), "mcp"],
    )
    async with Client(launch) as host:
        result = await host.call_tool(
            "reverse", {"latitude": 12.97, "longitude": 77.59}
        )
        assert not result.is_error and result.structured_content is not None
        assert result.structured_content["result"] == expected


if __name__ == "__main__":
    asyncio.run(check(Path(sys.argv[1])))

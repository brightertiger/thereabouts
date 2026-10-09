"""Public console entry, batch files and the optional MCP host."""

import asyncio
import json
from pathlib import Path

from mcp import Client, StdioServerParameters

from thereabouts import Geocoder

from .helpers import CONSOLE, FIXTURES, console, install_fixture


def test_file_batch_and_selected_fields(tmp_path: Path) -> None:
    install_fixture(tmp_path, FIXTURES / "packs/core-sample")
    points = tmp_path / "points.csv"
    points.write_text(
        'id,north,east,note\n7,48.8566,2.3522,"comma, quote ""x"""\n8,91,0,bad\n'
    )
    result = console(
        tmp_path,
        "reverse",
        str(points),
        "--lat-col",
        "north",
        "--lon-col",
        "east",
        "--fields",
        "status,country.code",
        "--format",
        "ndjson",
    )
    assert result.returncode == 5, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert rows[0]["id"] == "7" and rows[0]["note"] == 'comma, quote "x"'
    assert rows[0]["thereabouts_country.code"] == "FR"
    assert rows[1]["thereabouts_status"] == "invalid_input"
    assert set(rows[0]) == {
        "id",
        "north",
        "east",
        "note",
        "thereabouts_status",
        "thereabouts_country.code",
    }
    assert console(tmp_path, "reverse", "--version").returncode == 0
    assert console(tmp_path, "--fields").returncode == 0
    bad = tmp_path / "bad.ndjson"
    bad.write_text('bad first row\n{"lat":48.8566,"lon":2.3522}\n')
    result = console(tmp_path, "reverse", str(bad), "--quiet")
    assert result.returncode == 5
    assert not result.stderr
    assert len(result.stdout.splitlines()) == 2


def test_real_console_mcp_returns_current_result_json(tmp_path: Path) -> None:
    install_fixture(tmp_path, FIXTURES / "packs/core-sample")
    with Geocoder(data_dir=tmp_path) as geo:
        expected = geo.reverse(lat=48.8566, lon=2.3522).to_dict()

    async def check() -> None:
        params = StdioServerParameters(
            command=str(CONSOLE),
            args=["--data-dir", str(tmp_path), "mcp"],
        )
        async with Client(params) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert names == {
                "reverse",
                "h3",
                "geocode",
                "postal",
                "airport",
                "locode",
                "phone",
                "ip",
                "plate",
                "describe",
            }
            dictionary = (
                await client.read_resource("thereabouts://dictionary")
            ).contents
            assert "thereabouts-data-dictionary-1" in str(dictionary[0])
            value = await client.call_tool("reverse", {"lat": 48.8566, "lon": 2.3522})
            assert not value.is_error
            assert value.structured_content == expected

    asyncio.run(asyncio.wait_for(check(), timeout=15))
    eof = console(tmp_path, "mcp")
    assert eof.returncode == 0 and not eof.stdout


def test_empty_ndjson_and_missing_mcp_data(tmp_path: Path) -> None:
    store = tmp_path / "store"
    install_fixture(store, FIXTURES / "packs/core-sample")
    empty = tmp_path / "empty.ndjson"
    empty.write_text("")
    result = console(store, "reverse", str(empty), "--json")
    assert result.returncode == 0 and json.loads(result.stdout) == {"results": []}
    missing = console(tmp_path / "absent", "mcp")
    assert missing.returncode == 3
    assert missing.stderr.splitlines() == [
        "core data is not installed. Install it with:",
        "thereabouts data install core",
    ]


def test_current_mcp_missing_extra_message(tmp_path: Path) -> None:
    import subprocess
    import sys

    script = """
import sys
from importlib.abc import MetaPathFinder
class BlockMCP(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp" or fullname.startswith("mcp."):
            raise ModuleNotFoundError("MCP deliberately absent", name="mcp")
sys.meta_path.insert(0, BlockMCP())
from thereabouts import _core
assert not any(n.startswith("mcp") for n in sys.modules)
raise SystemExit(_core.run_cli(["thereabouts", "--data-dir", sys.argv[1], "mcp"]))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 2 and not result.stdout
    assert "install thereabouts[mcp] explicitly" in result.stderr

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from tests.conformance.generate import FIXTURES
from thereabouts.client import Geocoder
from thereabouts.commandline.application import main
from thereabouts.installing.install import install
from thereabouts.packs.jsonio import sha256

ROOT = Path(__file__).parents[2]


def test_local_host_uses_actual_stdio_and_all_three_families(tmp_path: Path) -> None:
    store = tmp_path / "store"
    for family in ("reverse", "postal", "airports"):
        source = FIXTURES / "codes" / family
        install(
            str(source),
            data_dir=store,
            manifest_sha256=sha256(source / "manifest.json"),
            offline=True,
        )

    async def check() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "tests.mcp.stdio_server",
                "--data-dir",
                str(store),
                "mcp",
                "--families",
                "reverse",
                "postal",
                "airports",
            ],
            cwd=ROOT,
            env={"TMPDIR": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        async with Client(params) as client:
            assert (
                client.server_info is not None
                and client.server_info.name == "Thereabouts"
            )
            with Geocoder(
                data_dir=store, packs=["reverse", "postal", "airports"]
            ) as reference:
                result = await client.call_tool(
                    "reverse_many", {"points": [[12.97, 77.59], [0, 180]]}
                )
                expected = [
                    row.to_dict()
                    for row in reference.reverse_many([(12.97, 77.59), (0, 180)])
                ]
                assert result.structured_content is not None
                assert result.structured_content["results"] == expected
                assert result.structured_content["count"] == 2
                result = await client.call_tool(
                    "resolve",
                    {"request": {"kind": "postal", "value": "00100", "country": "AA"}},
                )
                assert result.structured_content is not None
                assert (
                    result.structured_content["result"]
                    == reference.postal("00100", country="AA").to_dict()
                )
                result = await client.call_tool(
                    "resolve",
                    {"request": {"kind": "airport", "value": "ZZZ", "scheme": "iata"}},
                )
                assert result.structured_content is not None
                assert result.structured_content["result"]["status"] == "ambiguous"
                assert result.structured_content["result"]["selected"] is None
                result = await client.call_tool(
                    "install", {"source": "https://example.invalid"}
                )
                assert result.is_error

    asyncio.run(asyncio.wait_for(check(), timeout=15))


def test_cli_eof_exits_cleanly_and_does_not_print_json_banners(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.mcp.stdio_server",
            "--pack",
            str(FIXTURES / "serving"),
            "mcp",
        ],
        input="",
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=10,
        env={"TMPDIR": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0 and result.stdout == ""
    assert "Traceback" not in result.stderr


def test_optional_sdk_is_not_imported_by_lookup_and_missing_extra_is_clear() -> None:
    script = """
import sys
from importlib.abc import MetaPathFinder
class BlockMCP(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp" or fullname.startswith("mcp."):
            raise ModuleNotFoundError("MCP intentionally absent", name="mcp")
sys.meta_path.insert(0, BlockMCP())
from thereabouts.commandline.application import main
from thereabouts.client import Geocoder
with Geocoder("tests/fixtures/serving") as geo:
    assert geo.reverse(12.97, 77.59).status == "matched"
assert not any(name.startswith(("mcp", "pydantic")) for name in sys.modules)
raise SystemExit(main(["--pack", "tests/fixtures/serving", "mcp"]))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 2 and result.stdout == ""
    assert "install thereabouts[mcp] explicitly" in result.stderr


def test_conflicting_startup_selection_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(["--pack", str(FIXTURES / "serving"), "mcp", "--families", "reverse"]) == 2
    )

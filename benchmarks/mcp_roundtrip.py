"""Measure local stdio transport on an explicitly selected small reverse pack."""

import argparse
import asyncio
import json
import platform
import resource
import statistics
import sys
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from mcp import Client, StdioServerParameters

from thereabouts.packs.jsonio import sha256


async def measure(pack: Path, queries: Path) -> dict[str, Any]:
    points = np.load(queries)[:1000].tolist()
    args = StdioServerParameters(
        command=sys.executable,
        args=["-m", "thereabouts.commandline.application", "--pack", str(pack), "mcp"],
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    start = perf_counter()
    async with Client(args) as client:
        startup = perf_counter() - start
        warmup = await client.call_tool("reverse_many", {"points": points})
        assert not warmup.is_error
        single = []
        for latitude, longitude in points[:100]:
            start = perf_counter()
            answer = await client.call_tool(
                "reverse", {"latitude": latitude, "longitude": longitude}
            )
            assert not answer.is_error
            single.append(perf_counter() - start)
        elapsed = []
        for _ in range(3):
            start = perf_counter()
            batch = await client.call_tool("reverse_many", {"points": points})
            assert not batch.is_error
            elapsed.append(perf_counter() - start)
        payload_bytes = len(batch.model_dump_json(by_alias=True).encode())
        info = (await client.call_tool("info")).structured_content
    scale = 1 if sys.platform == "darwin" else 1024
    return {
        "machine": {
            "system": platform.platform(),
            "python": platform.python_version(),
            "mcp": version("mcp"),
            "pydantic": version("pydantic"),
        },
        "sample": {
            "pack_manifest_sha256": sha256(pack / "manifest.json"),
            "queries_sha256": sha256(queries),
            "batch_points": len(points),
            "returned_rows_per_page": 20,
            "scalar_requests": len(single),
        },
        "startup_seconds": startup,
        "scalar_roundtrip_median_ms": statistics.median(single) * 1000,
        "scalar_roundtrip_max_ms": max(single) * 1000,
        "batch_page_roundtrip_seconds": elapsed,
        "batch_tool_payload_bytes": payload_bytes,
        "parent_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * scale,
        "server_peak_rss_bytes": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        * scale,
        "backend": None if info is None else info["backend"],
        "notes": [
            "Synthetic populated sample; not a world benchmark.",
            "Round trips include schemas, text/structured JSON and pipe transfer.",
            "Payload excludes the JSON-RPC envelope; no external host UI is involved.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(measure(args.pack.resolve(), args.queries))
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

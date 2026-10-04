# Local MCP lookup server

> Historical format-1 MCP documentation. Current commands, data store and
> MCP are documented in [CLI.md](../CLI.md); the current Python API is in
> [CLIENT_STATUS.md](../CLIENT_STATUS.md). Legacy console examples require
> `python -m thereabouts.commandline.application` in place of `thereabouts`.

`thereabouts mcp` serves read-only place lookups over standard input/output. It
uses the same Python reader, selected installed packs, methods and result
semantics as the CLI. It does not install data or expose arbitrary filesystem
paths as tools. An operator selects packs before starting the process.

The adapter uses the official [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/),
pinned to **2.2.0**, through its `MCPServer` API. The optional `mcp` extra contains
the SDK and its dependencies; the base reader still depends only on NumPy and H3.
A base lookup does not import MCP or Pydantic. SDK 2.2.0 is tested here rather than
assuming the older FastMCP interface; the [SDK client documentation](https://py.sdk.modelcontextprotocol.io/client/)
describes the reference host used below.

## Start with explicitly installed data

From this checkout, prepare its own environment with `uv sync --extra mcp`. For
an application, install the `mcp` extra on an approved local Thereabouts wheel,
for example `pip install '/media/thereabouts-0.1.0-py3-none-any.whl[mcp]'` with
an offline dependency cache when needed. No Thereabouts package is published by
this work. Install packs using the explicit commands in
[DATA_INSTALLATION.md](format-1-data-installation.md), then launch:

```sh
thereabouts --data-dir /data/thereabouts mcp --families reverse postal airports
```

Omit `--families` to select reverse only. For a standalone directory use
`thereabouts --pack /data/reverse-pack mcp`. These are startup arguments, never
model-callable parameters. The usual `THEREABOUTS_DATA` and platform defaults
apply. Selected families must have compatible catalogue epochs and golden/policy
identities. Restart to select updated data. EOF shuts down the reader; protocol
messages use stdout and diagnostics use stderr. No HTTP listener is started.

A host's stdio configuration can launch the installed executable directly:

```json
{
  "mcpServers": {
    "thereabouts": {
      "command": "/apps/geo/.venv/bin/thereabouts",
      "args": ["--data-dir", "/data/thereabouts", "mcp",
               "--families", "reverse", "postal", "airports"]
    }
  }
}
```

Replace these operator-owned paths. This is the common stdio configuration
shape, not a claim that a particular desktop host was tested. The tested host is
the SDK `Client` launching the actual CLI in a subprocess; no package runner or
startup download is involved.

## Tools and pagination

All five tools advertise read-only, idempotent, non-destructive and closed-world
annotations. `info` reports selected manifest hashes, versions, source attribution,
notice paths, cache state and transport limits.

| Tool | Input | Output |
| --- | --- | --- |
| `reverse` | Numeric `latitude`, `longitude` | One result page |
| `reverse_many` | At most 1,000 numeric coordinate pairs; optional `errors`, `offset`, `limit` | Ordered result page |
| `resolve` | Typed `request`; optional `offset`, `limit` | Candidate page |
| `explain` | Same typed request and page controls | `{page, raw_evidence_installed:false}` |
| `info` | None | Selected pack metadata and limits |

A typed request is one of:

```json
{"kind":"coordinates","latitude":12.97,"longitude":77.59}
{"kind":"h3","cell":"8860145b4bfffff"}
{"kind":"postal","value":"00100","country":"AA"}
{"kind":"airport","value":"ZZZ","scheme":"iata"}
```

The codes/countries in these examples are synthetic fixture identifiers. Postal
country and airport scheme remain explicit context; local airport codes also
require country. Input models reject unwanted fields and do not coerce strings
or booleans into coordinates. Core errors are reported as tool errors with their
class/message; invalid request shapes are SDK schema errors. Unknown tools fail.
Ordinary no-match remains a normal result.

A result page contains `result` (the public Python JSON), `total_candidates`,
`offset`, `limit`, `next_offset` and `truncated`. Default and maximum `limit` are
**20**; `offset` is a nonnegative integer. Follow `next_offset` with the same
request until it is null. Only `result.candidates` is paged: `status`, `selected`,
methods, warnings, data identity and evidence retain their original meanings.
In particular, a one-candidate page from an ambiguous answer is still ambiguous
and has `selected: null`.

A batch page contains `results`, `count` (returned rows), `total_results`,
`offset`, `limit`, `next_offset` and `truncated`. It returns at most **20** full
results, preserving input order. Each request validates/geocodes all its input
pairs, even when returning a later page, so `errors: "raise"` consistently rejects
any invalid coordinate. `errors: "collect"` places out-of-range coordinates in
`invalid_input` rows. Non-numeric pairs fail request schema validation before
lookup. Empty batches return zero rows without truncation. For large enrichment
jobs, the Python column API avoids transport and repeated evidence serialization.

The 1,000-point input cap comes from the product plan. The page size comes from
measurement: the largest fixture candidate is 4,825 compact UTF-8 bytes, and a
20-row page on the larger reverse sample is about 349 KB including both SDK text
and structured content. This is a count limit, not a guaranteed byte or memory
bound for arbitrary future data. Output schemas specify result-envelope/page
fields; the core owns nested place/evidence semantics, checked against shared
vectors. The adapter does not recursively revalidate every nested JSON value.

## Tested reference host

A minimal headless host uses the same startup command:

```python
import asyncio
from mcp import Client, StdioServerParameters

async def main():
    launch = StdioServerParameters(
        command="/apps/geo/.venv/bin/thereabouts",
        args=["--data-dir", "/data/thereabouts", "mcp"],
    )
    async with Client(launch) as host:
        reply = await host.call_tool(
            "reverse_many", {"points": [[12.97, 77.59], [0, 180]]}
        )
        if reply.is_error:
            raise RuntimeError(reply.content)
        print(reply.structured_content)

asyncio.run(main())
```

`tests/mcp/test_stdio.py` runs this flow with all three installed fixture families,
checks coordinate enrichment and postal joins against Python, preserves ambiguous
airport results, rejects an installation-tool request and checks clean EOF.
Networking is forbidden in the test host and server child. Other tests check
shared result serialization, schemas, oversized requests, page continuation,
whole-request error handling, missing optional SDK and base-import isolation.
An external host UI and remote transport are deliberately unverified.

## Measurements and corrected memory incident

[CLIENT_MCP_MEASUREMENTS.json](../measurements/CLIENT_MCP_MEASUREMENTS.json) uses the populated
synthetic 4,176-place / 308,032-row / 64-block pack on Apple M2, 8 GiB RAM,
macOS 27 arm64, CPython 3.12.8, MCP SDK 2.2.0 and Pydantic 2.13.5. The SDK host
starts the actual stdio server. Connection/startup took **0.419 s**; 100 warmed
scalar requests had median **1.293 ms**, maximum **6.256 ms**. Three 1,000-point
requests returning the first 20 rows took **21.8–36.4 ms**. Each page was
**349,381 bytes**, excluding the small JSON-RPC envelope. Host/server peak RSS
was **94,044,160 / 97,550,336 bytes**. This measures the complete protocol round
trip, not the core's microsecond lookup path.

The initial full-output probe is retained in
[CLIENT_MCP_INITIAL_MEASUREMENTS.json](../measurements/CLIENT_MCP_INITIAL_MEASUREMENTS.json):
a 1,000-row reply was **17,467,570 bytes**, with **1,990,803,456 bytes** host peak
RSS and **515,293,184 bytes** server peak. That probe exceeded the owner's 1.5 GB
process budget and ended before corrective work. A subsequent 50-row CPU profile
placed client output-schema validation at 11 ms of a 49 ms round trip; it does
not isolate the cause of every memory allocation. Paging and replacing recursive
JSON-union validation with envelope validation corrected the measured resource
problem. Small preliminary rechecks preceded the final 1,000-input test. No main
checkout data was read or written, and no world job was launched.

Reproduce from this checkout after generating the populated sample:

```sh
TMPDIR="$PWD/.cache/tmp" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -m benchmarks.mcp_roundtrip \
  --pack .cache/populated-sample/pack \
  --queries .cache/populated-sample/shuffled.npy \
  --output .cache/mcp-measurements.json
```

# Node client

Offline geographic context for Node 22 or 24. ESM only, with TypeScript
declarations. The Rust core ships as WebAssembly, so installing needs no
compiler and there are no native add-ons. No data is bundled.

~~~sh
npm install thereabouts
npx thereabouts data install core postal airports     # see data-install.md
~~~

## Open a geocoder

~~~js
import { Geocoder } from "thereabouts";

const geo = await Geocoder.open({ dataDir: "./store" });
try {
  console.log(await geo.reverse({ lat: 48.8566, lon: 2.3522 }));
} finally {
  await geo.close();
}
~~~

| Call | Opens |
| --- | --- |
| `Geocoder.open()` | the store found through `THEREABOUTS_DATA`, then the platform data directory |
| `Geocoder.open({ dataDir })` | that store |
| `Geocoder.open({ pack: "/one/pack" })` | one pack, standalone |
| `Geocoder.open({ packs: { core, postal } })` | explicit packs from one dataset |
| `Geocoder.open({ verify: true })` | the same, with full checksum and structure verification |

`await using` works through `Symbol.asyncDispose`. The module-level `reverse`
opens the default store on first use.

## Lookups

Every method returns a promise and accepts `evidence: true`.

~~~js
await geo.reverse({ lat: 48.8566, lon: 2.3522 });
await geo.fromH3("881fb46625fffff");
await geo.geocode("Paris", { country: "FR", limit: 5 });  // subdivision, prefer: "population"
await geo.postal("75001", { country: "FR" });             // country is required
await geo.airport("CDG", { scheme: "iata" });             // iata, icao, gps, local, ident
await geo.locode("FRPAR");
await geo.phone("+33 1 2345 6789");
await geo.ip("8.8.8.8");
await geo.plate("AB-123-CD", { country: "FR" });          // series
~~~

Each forward verb needs its pack. Geocoding needs `core` and finds towns and
cities, not street addresses. With `core` installed, forward results also carry
the canonical city and timezone; standalone forward packs leave them null.

## Results

Results are deeply frozen snake_case JSON objects, identical in shape to Python
and the command line: `status`, `kind`, `match`, `point`, `cell`, `city`, `state`,
`country`, `timezone`, `distance_band`, `candidates`, `rank_basis` and optional
`evidence` and `hint`. Use `structuredClone(result)` for a mutable copy. Results
survive `close()`; queries after it fail.

`status` is one of `matched`, `ambiguous` (ranked candidates), `not_found`,
`invalid_input` (read `hint`) or `unsupported_granularity`. Cell-centre
coordinates can differ from Python by a few floating-point ULPs, so compare them
within 1e-10 degrees.

## Batches

~~~js
const points = [{ lat: 48.8566, lon: 2.3522 }, { lat: 1.3521, lon: 103.8198 }];
for await (const result of geo.reverseMany(points)) {
  console.log(result.country?.code);
}
~~~

`reverseMany` takes a sync or async iterable of named points, keeps order and
holds one result at a time. Bare coordinate pairs are rejected.

## Errors and performance

Invalid query values return `invalid_input`. Missing or damaged data raises a
`ThereaboutsError` subclass with a stable `code`: `DataNotInstalledError`
(the message names the install command), `IncompatibleDataError`,
`CorruptPackError`, `ClosedGeocoderError`, `PackNotFoundError`,
`ResourceLimitError`, `InvalidInputError` and `InternalError`.

The WebAssembly host reads pack files with synchronous positioned reads. Scalar
methods return promises but do the work on the calling thread, so run heavy
batches in a worker thread when the event loop must stay responsive.

## Command line

`npx thereabouts` runs the same command tree as the Python and native consoles.
See [cli.md](cli.md). The `mcp` command delegates to the Python MCP server, so
install `thereabouts[mcp]` in a Python environment first; set `THEREABOUTS_PYTHON`
to choose the interpreter (default `python3`). See [mcp.md](mcp.md).

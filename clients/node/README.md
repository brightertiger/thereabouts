# Thereabouts for Node

Offline geographic context from one Rust core compiled to WebAssembly.
Node 22 or 24, ESM, with TypeScript declarations. No geographic data is bundled,
and lookups never download data. The package version is 0.1.0; it has not been
published. The registry's 0.0.1 placeholder is replaced only by the owner's
0.1.0 publication. Code licensing remains UNLICENSED pending the owner's decision.

~~~js
import { Geocoder } from "thereabouts";

const geo = await Geocoder.open({ dataDir: "./store" });
try {
  console.log(await geo.reverse({ lat: 48.8566, lon: 2.3522 }));
  console.log(await geo.geocode("Paris", { country: "FR", limit: 5 }));
  console.log(await geo.postal("75001", { country: "FR" }));
  console.log(await geo.airport("CDG", { scheme: "iata" }));
  console.log(await geo.locode("FRPAR"));
  console.log(await geo.phone("+33 1 2345 6789"));
  console.log(await geo.ip("8.8.8.8"));
  console.log(await geo.plate("AB-123-CD", { country: "FR" }));
  for await (const result of geo.reverseMany([{ lat: 48.8566, lon: 2.3522 }])) {
    console.log(result.city?.name);
  }
} finally {
  await geo.close();
}
~~~

fromH3(cell, {evidence}) resolves stored ancestors at resolutions zero through
eight. geocode finds towns and cities; street addresses are unsupported.
Its options are country, subdivision, limit, prefer ("population"), scope
("cities") and evidence. Airport also accepts country for local codes; LOCODE
and phone accept country; plate accepts country and series. All verbs accept
evidence. Reverse takes a named coordinate object; bare coordinate pairs are
rejected. Invalid query values return invalid_input; corrupt or incompatible
packs raise coded error classes. Missing data names the exact install command.

Results are deeply frozen, detached snake_case JSON objects. Ambiguity retains
only the flat fields shared by every candidate, plus ranked candidates.
structuredClone(result) makes a mutable copy. Results survive close();
queries and suspended iterators fail after close. reverseMany accepts sync
or async iterables, preserving order with one result at a time. reverse at
module level lazily opens the default store. Scalar methods return promises;
the WASM host uses synchronous positioned reads, so heavy work should run in
a Node worker when event-loop isolation is needed.

Geocoder.open({pack: "/one/pack"}) selects a standalone family.
Geocoder.open({packs: {core: "/core", postal: "/postal"}}) attaches explicit
families from one dataset. Forward packs with a matching core gain city detail
and time zones; standalone forward packs retain their own source fields and
have null city/timezone detail. Catalogue pins are checked before enrichment.
verify: true checks full checksums and structures. Normal open checks
manifests, inventory and sizes. Keep pack files immutable.

## Install an artifact

Build with npm pack from this directory, then install the resulting
thereabouts-0.1.0.tgz in your application with npm install /path/to/the/archive.
The Node workflow builds and tests on 22 and 24 and retains that tarball.
No workflow has been run remotely; publication requires a manually approved tag.
See repository docs/CLIENT_RELEASE.md and LICENSE-DECISION.md.

## Commands and data

~~~sh
npx thereabouts --data-dir ./store data install core postal --from ./release --yes
npx thereabouts --data-dir ./store reverse --lat 48.8566 --lon 2.3522 --json
npx thereabouts --data-dir ./store reverse points.csv --csv
npx thereabouts --data-dir ./store data verify --full
~~~

The command grammar is specified in repository docs/CLI.md; the wire format
is specified in docs/PACK_FORMAT.md. There is no separate JavaScript decoder.
Table/JSON/NDJSON/CSV rendering, field projection, streaming batch parsing and
lookup exit status come from the shared Rust CLI module. JavaScript hosts the
shared command grammar and owns process IO. mcp delegates to the optional installed Python
MCP host (THEREABOUTS_PYTHON overrides the default python3 executable).

The store is shared with Python/native: packs/<family>/<dataset-version>
and active.json, with old family pointers still discoverable. Discovery uses
dataDir, THEREABOUTS_DATA, then the platform user-data directory. No release
service is published: explicitly configure --from or THEREABOUTS_RELEASE_URL.
Install uses Node fetch, exact Range resume, sha256, strict ustar extraction,
WASM pack verification and atomic activation. An interrupted transfer resumes
on the next explicit install. HTTPS redirects cannot downgrade. The only
runtime npm dependency is undici for environment proxy support; there are no
native add-ons or platform packages.

Native and Node installs share an exclusively created `.lock` file in the store.
The lease records PID, creation time and a unique token. Live contention exits
2 with “another install is running”; dead owners are recovered automatically,
with a short grace period for incomplete records. A live PID never expires by
age. If the OS reuses a dead installer's PID, its stale lease can therefore
block installation: inspect `.lock`, confirm the named process is unrelated and
that no install is running, then remove `<data-dir>/.lock` and retry. Never
remove a live installer's lease. No coordination socket is used.

## Build and validation

From the repository, with Rust 1.99 and wasm32-unknown-unknown installed:

~~~sh
cargo install wasm-bindgen-cli --version 0.2.129 --locked
npm ci --ignore-scripts
npm run build
npm test
npm run check
npm run format
~~~

WASM_BINDGEN can select the installed wasm-bindgen binary. The build script
uses the workspace Cargo.lock and release profile, then wasm-bindgen's ESM
web target. The generated pkg/ directory is ignored by Git and included in
the npm files whitelist. npm prepack rebuilds it; consumers load the packaged
artifact and need no Rust compiler or build step. Nothing is published by
the build script.

Tests drive the same 478 current/synthetic vectors as Rust and Python, plus
54 original legacy assertions with explicit migration allowances. CLI tests
document typed and NUL argv boundaries rather than silently coercing them.
Numeric comparisons use Rust conformance's 1e-10 absolute tolerance for
cross-target H3 floating-point arithmetic. Transfers use local directories and
loopback HTTP only. Benchmarks are generated by
node benchmarks/node_read_path.mjs from the repository root; recorded
numbers and qualification are in docs/CLIENT_STATUS.md and
docs/measurements/CLIENT_NODE_MEASUREMENTS.json. npm type checks cover declarations and
consumer examples; runtime JS behavior is covered by node --test.

H3-derived cell-centre coordinates can differ from native results by a few
floating-point ULPs. Compare these values within 1e-10 degrees; serialized
number text is not a byte-identity contract. Other result fields and candidate
ordering share exact conformance.

Both command hosts consume one JSON grammar and Rust parser/help renderer.
Store paths use the same portable policy as Python. Explicit pack selections
open their handles immediately; discovery through a store defers each family
until its first lookup (verify: true opens all selected families for verification).
All opened handles remain held until close or async disposal.

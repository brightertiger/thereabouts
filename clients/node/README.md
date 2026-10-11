# Thereabouts for Node

Offline geographic context from one Rust core compiled to WebAssembly:
coordinates, H3 cells, town names, postal codes, airports, UN/LOCODEs, phone
numbers, IP addresses and vehicle plates. Node 22 or 24, ESM, with TypeScript
declarations. No compiler is needed to install. No geographic data is bundled,
and lookups never download data. The code is MIT licensed.

~~~sh
npm install thereabouts
npx thereabouts data install core postal airports
~~~

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

## Commands and data

~~~sh
npx thereabouts --data-dir ./store data install core postal
npx thereabouts --data-dir ./store reverse --lat 48.8566 --lon 2.3522 --json
npx thereabouts --data-dir ./store reverse points.csv --csv
npx thereabouts --data-dir ./store data verify --full
~~~

The command grammar is specified in the repository's [cli.md](https://github.com/brightertiger/thereabouts/blob/main/docs/clients/cli.md);
the wire format is specified in [pack-format.md](https://github.com/brightertiger/thereabouts/blob/main/docs/dataset/pack-format.md). There is no separate JavaScript decoder.
Table/JSON/NDJSON/CSV rendering, field projection, streaming batch parsing and
lookup exit status come from the shared Rust CLI module. JavaScript hosts the
shared command grammar and owns process IO. mcp delegates to the optional installed Python
MCP host (THEREABOUTS_PYTHON overrides the default python3 executable).

The store is shared with Python/native: packs/<family>/<dataset-version>
and active.json, with old family pointers still discoverable. Discovery uses
dataDir, THEREABOUTS_DATA, then the platform user-data directory. The default
release is the project's GitHub releases; THEREABOUTS_RELEASE_TOKEN (or
GITHUB_TOKEN) reads them while the repository is private, and --from or
THEREABOUTS_RELEASE_URL selects another source. `data install dataset` restores
the Parquet dataset under dataset/<version>/.
Install uses Node fetch, exact Range resume, sha256, strict ustar extraction,
WASM pack verification and atomic activation. An interrupted transfer resumes
on the next explicit install. Redirects cannot downgrade from HTTPS, and the
token goes only to the GitHub API origin, never across a redirect. The only
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

## More

[Node guide](https://github.com/brightertiger/thereabouts/blob/main/docs/clients/node.md), [installing data](https://github.com/brightertiger/thereabouts/blob/main/docs/clients/data-install.md),
[command line](https://github.com/brightertiger/thereabouts/blob/main/docs/clients/cli.md), [MCP server](https://github.com/brightertiger/thereabouts/blob/main/docs/clients/mcp.md) and
[contributing](https://github.com/brightertiger/thereabouts/blob/main/.github/CONTRIBUTING.md).

# Thereabouts clients: one Rust core, three thin surfaces

Status: draft for owner review, 2026-10-03. Companion to
`2026-10-03-pipeline-redesign-design.md`, which produces the dataset these
clients read.

## 1. Purpose

Thereabouts should answer two questions offline, from one installed dataset,
in Python, in Node and at the command line:

- **Reverse:** where is this coordinate or H3 cell? → country, subdivision,
  canonical city, time zone, with the method behind the answer.
- **Forward (geocode):** where is this thing? → a city or town by name (with a
  country hint), a postal code, an airport code, a UN/LOCODE, an IP address, a
  phone number, a vehicle plate. Street addresses are out of scope; the
  dataset is city-level and the tools say so.

Success means:

1. `pip install thereabouts`, `npm install thereabouts` and the `thereabouts`
   command exist, do both directions, and behave identically.
2. Every lookup family is implemented once.
3. A single lookup takes microseconds; a million-row batch is columnar.
4. Nothing is guessed: input kinds are explicit, not-found is a status, and
   every forward result says what kind of thing matched and how.

Owner decisions: the core is Rust (pyo3 for Python, WebAssembly for Node);
forward inputs are city/town names, postal/airport/LOCODE codes, IP, phone and
plates, not free-text addresses; the audience is batch data work and
application developers equally; simplicity over cleverness.

## 2. Why one core

Today the pack format is implemented twice by hand (about 2,440 lines of
Python and 1,990 of JavaScript) with a copied specification that has already
drifted, and six more lookup families are needed. A Cython kernel saves 3 µs
of a 10 µs lookup at the price of a wheel matrix that never ran in CI. Fuzzy
name matching over millions of names is not realistic in pure Python or JS.

One Rust crate owns the format (reader and writer), every lookup, and the
command-line logic. Python and Node are thin: argument conversion, idiomatic
result objects, data discovery. The 54 existing conformance vectors, extended
per family, prove the three surfaces agree.

What is removed: `src/thereabouts/` v1 runtime (700 lines), the new Python
reader (`packs/`, `reading/`, Cython), the JavaScript reader
(`clients/node/src/`), `build_data/serve*` exporters (the pipeline's `packs`
stage calls the core's writer instead), `clients/node/FORMAT.md`.

## 3. Layout

```
core/                              Rust workspace
  thereabouts-core/                format, packs, lookups, result model
  thereabouts-cli/                 clap command tree; `run(argv, io) -> exit code`
  thereabouts-py/                  pyo3 module `thereabouts._core` (abi3)
  thereabouts-wasm/                wasm-bindgen module + host IO interface
src/thereabouts/                   Python package: thin layer over _core
clients/node/                      npm package: wasm + loader + typed API + bin
docs/PACK_FORMAT.md                the one specification (version 2)
tests/conformance/                 vectors shared by core, Python and Node
```

Rust modules stay small and single-purpose like the Python house style:
one file per pack family, one per lookup, one for the result model.

## 4. Data: packs

The dataset published to S3 is Parquet for analysts. Clients read **packs**:
compact binary files built from the dataset by the pipeline's `packs` stage
through the core's writer. Format version 2 keeps the proven spatial layout
of version 1 (resolution-3 block directory, sparse keys for stored cells at
resolutions 3–8, dictionary-coded labels) and adds families.

| Pack | Contents | Required for | Size (estimate) |
|---|---|---|---|
| `core` | reverse cells, place catalogue with centroid, population and time zone, countries and subdivisions metadata, canonical-city names index | `reverse`, `geocode` | 400–900 MB |
| `postal` | postal codes → place, point | `postal` | ~60 MB |
| `airports` | IATA/ICAO/GPS/local codes | `airport` | ~5 MB |
| `locode` | UN/LOCODE | `locode` | ~5 MB |
| `ip` | sorted IPv4/IPv6 intervals → country, region, city | `ip` | ~120 MB |
| `phone` | calling codes, prefix trie, metadata | `phone` | ~5 MB |
| `plates` | per-country format rules, state/series tables | `plate` | ~2 MB |
| `names-full` | all 6.9M place names with alternates, for `geocode(..., scope="places")` | optional | 100–250 MB |

Sizes are estimates from table row counts; the first world export measures
them and the numbers in docs are then the measured ones.

Name index: NFKC, casefold, diacritics folded for Latin/Cyrillic/Greek (CJK
left intact), punctuation and whitespace collapsed, `Saint/St.` style
expansions from a small table carried in the pack. Keys map to catalogue
references through an FST; a trigram index gives typo tolerance as a
fallback. Ranking is population within the hard filter of country or
subdivision when given, and is reported as `rank_basis: "population"`.
The normalisation rules are data in the pack manifest so the writer and
reader never disagree.

Time zone: the `packs` stage joins `timezone_cells` onto stored cells so
reverse answers carry an IANA zone; `zone_tables` are included for offsets.

Every pack has a manifest: format version, dataset version, family, shard
checksums, licence notices, attribution. Packs from different dataset
versions do not mix; the store keeps one active dataset version.

## 5. Public interface

### 5.1 Result model (one definition, in the core)

```
Result
  status:   matched | ambiguous | not_found | invalid_input | unsupported_granularity
  kind:     cell | city | postal | airport | trade_location | ip_range | phone_prefix | plate
  match:    exact | alternate_name | fuzzy | contained | nearest | nearest_distant   (how)
  country:  {code, code3, name} | null
  state:    {code, name} | null
  city:     {id, name, name_en, kind, population, point} | null
  timezone: IANA name | null
  point:    {lat, lon} representative point | null        (cell centre or place centroid)
  cell:     H3 resolution-8 id | null
  distance_km: for nearest matches | null
  candidates: [Result] when ambiguous, ranked, with rank_basis
  evidence: optional detail (method chain, source ids) behind an explicit flag
```

Not-found is a status, never an exception. Missing is `null`, never `""` or
`0`. The flat fields above are what people need daily; evidence is opt-in.

### 5.2 Library

Python (sync; the core releases the GIL in batch calls):

```python
from thereabouts import Geocoder, reverse            # reverse(): module-level shortcut
with Geocoder() as geo:                              # discovery; never downloads
    r = geo.reverse(lat=48.8566, lon=2.3522)         # keyword-only
    r.status, r.city.name, r.country.code, r.timezone, r.match
    geo.from_h3("8860145b49fffff")
    g = geo.geocode("Lyon", country="FR", limit=5)   # cities and towns only
    geo.postal("75001", country="FR"); geo.airport("CDG"); geo.locode("INBOM")
    geo.ip("8.8.8.8"); geo.phone("+91 22 1234 5678"); geo.plate("MH 12 AB 1234", country="IN")
    cols = geo.reverse_columns(lat_array, lon_array)  # dict of NumPy arrays, Arrow-ready
    for r in geo.reverse_many(points): ...            # iterator, input order
```

Node (async-first ESM, same names in camelCase):

```js
import { Geocoder } from "thereabouts";
const geo = await Geocoder.open();                   // or { dataDir }
const r = await geo.reverse({ lat: 48.8566, lon: 2.3522 });
const g = await geo.geocode("Lyon", { country: "FR", limit: 5 });
for await (const x of geo.reverseMany(points)) {}
await geo.close();
```

Rules shared by both: `lat`/`lon` keyword or object only, never positional
pairs; `geocode` rejects code-shaped input (`75001`, `8.8.8.8`, `+44`) with
`invalid_input` and a hint naming the right method; address-shaped input
returns `unsupported_granularity`; ambiguity returns `candidates` with
`selected` null unless the caller opts into `prefer="population"`; errors
(`DataNotInstalledError`, `IncompatibleDataError`, `CorruptPackError`,
`ClosedGeocoderError`) carry a stable `code` and, for missing data, the exact
`thereabouts data install …` command. JSON serialisation uses `snake_case`
keys in both languages so one fixture serves all.

### 5.3 Command line

One binary's worth of logic, in the core, exposed as a Python console script
and an `npx` bin:

```
thereabouts reverse --lat 48.8566 --lon 2.3522        thereabouts reverse points.csv
thereabouts h3 8860145b49fffff                        thereabouts reverse - < points.ndjson
thereabouts geocode "Lyon, FR" [--limit 5]
thereabouts postal 75001 --country FR                 thereabouts airport CDG
thereabouts locode INBOM                              thereabouts ip 8.8.8.8
thereabouts phone "+91 22 1234 5678"                  thereabouts plate "MH 12 AB 1234" --country IN
thereabouts data install core [postal …] [--version] [--from URL|DIR]
thereabouts data list | verify [--full] | remove <pack> [--yes] | path | update --check
thereabouts info                                      thereabouts mcp
```

Output: a table on a TTY, NDJSON when piped, `--json`, `--csv`, `--fields`
(no value lists the fields, as `gh` does). Batch: a file or `-`, CSV
detected by an exact header list (`lat`, `lon`, `latitude`, `longitude`,
`lng`) else `--lat-col/--lon-col`; input columns pass through; a bad row
emits `status: invalid_input` and the run continues; exit codes 0 success,
2 usage, 3 data not installed, 4 data incompatible or corrupt, 5 some rows
failed. Data location: `--data-dir`, then `THEREABOUTS_DATA`, then the
platform user-data directory. No config file until something needs one.
`NO_COLOR` honoured. The first line of `geocode --help` reads: "Finds towns
and cities by name. Street addresses are not supported."

### 5.4 MCP

A thin optional server over the Python API exposing one tool per verb with
the same result JSON. It is kept because it exists and is small; it is not a
design driver.

## 6. Distribution

- **Python:** `maturin` builds one `abi3` wheel per platform (Linux x86_64 and
  aarch64 manylinux, macOS x86_64 and arm64, Windows x86_64) plus an sdist;
  `thereabouts` contains only the thin layer and `_core`. No pure-Python
  fallback: the sdist builds with cargo where no wheel fits.
- **Node:** one `.wasm` artifact built with `wasm-bindgen`, loaded by a small
  JS shim that supplies file reads (sync `fs` in Node) and the data store. No
  native add-on, no platform packages. If a workload later needs native speed,
  `napi-rs` can be added behind the same JS API.
- **CLI:** the Python console script and the npm `bin` both call the core's
  `run(argv)`. A standalone binary via GitHub releases is a later option.
- **Data:** never bundled, never downloaded implicitly. `data install` fetches
  from a release index (`index.json`: dataset versions → pack URLs, sizes,
  checksums) whose default URL is the S3 Open Data bucket once published; a
  mirror URL is configurable. Installs are atomic (download to a temp dir,
  verify, rename) and resumable; the store pins the active dataset version.

Versions: code (semver, per package), pack format (integer in the manifest),
dataset (`YYYY.MM`). A client states the format versions it reads and the
oldest dataset version it accepts.

## 7. Dependencies on the pipeline

The pipeline redesign running now must additionally produce, in its dataset:

1. a **`names`** table: `city_id`, `name`, `language`, `kind`
   (primary/english/alternate/ascii), `preferred`, `population`, `lat`,
   `lon`; built from `canonical_cities` and `places` joined to GeoNames
   alternate names in `normalized/geonames` by `geonames_id` (no reconciled
   data needed). Optionally the same for all places, feeding `names-full`.
2. **`plates`** as a dataset table (from `plate_country`).
3. **`packs`** stage calling the core's writer (`thereabouts._core.write_pack`)
   instead of `build_data/serve`; the pipeline depends on the client package,
   never the reverse.
4. Freedom to delete `src/thereabouts/` v1 modules: the pipeline moves what it
   still imports (`format`, `hierarchy`, `index`, `table`, `models`) into
   `pipeline/`; cell-id encoding for the dataset stays pipeline-side; the pack
   format's encoding is the core's.

These are queued as the pipeline agent's next tasks after its current work
packages; the client work can proceed on the existing dataset meanwhile
(names from `canonical_cities` only, no plates) and switch when the tables
exist.

## 8. Testing

- **Core:** unit tests per module; property tests for the format (round-trip
  write/read, corrupt-shard detection); the conformance vectors as integration
  tests.
- **Conformance bundle** (`tests/conformance/*.json`): vectors per family,
  generated once from the Python reference on a committed sample pack and run
  by the core, the Python layer, the CLI (as subprocess) and Node. Adding a
  family means adding its vectors first.
- **Sample pack:** built from a handful of countries of the real dataset
  (Benelux plus a few cities with ambiguity cases), small enough to commit
  (target under 5 MB), used by every test and every documented example.
- **Python and Node layers:** small tests for argument validation, result
  conversion, discovery and the install flow against a local directory
  source; no network (guard stays).
- **Performance:** one reproducible benchmark script per surface on the sample
  pack and, once a world pack exists, on it; numbers in docs come only from
  those scripts and name the machine.

## 9. Work packages

Each ends with tests green (`cargo test`, `pytest`, `node --test`, `ruff`,
`mypy`, `cargo clippy`, `cargo fmt --check`) and a commit; each is one
implementation plan; all on branch `feat/rust-core` in its own worktree.

1. **Core and Python reverse.** Crate skeleton; format v2 reader and writer
   for `core` (cells, catalogue with centroid/population/time zone,
   countries, subdivisions); result model; pyo3 binding; thin Python
   `Geocoder` with `reverse`, `from_h3`, `reverse_many`, `reverse_columns`;
   writer used by a Python script to build the sample pack from `data/golden`
   (read-only); conformance harness running the existing 54 vectors.
2. **Forward families.** `postal`, `airports`, `locode`, `ip`, `phone`,
   `plates` packs and lookups; the city names index (FST + trigram) from
   `canonical_cities` names (`names` table when available); vectors per
   family; `geocode` semantics from §5.2.
3. **CLI and data store.** clap tree in `thereabouts-cli`; Python console
   script; store, release index, `data` commands with atomic installs; table
   and NDJSON output; batch input; exit codes; MCP server re-pointed at the
   new API.
4. **Node.** `wasm-bindgen` build, host IO shim, typed API and `.d.ts`,
   `npx thereabouts` bin, conformance run; npm package made publishable
   (not published).
5. **Retirement and release engineering.** Delete v1 runtime, old readers,
   `build_data/serve*` (coordinated with the pipeline branch); wheel and npm
   workflows (not run until the owner says); README for each package; docs
   updated; placeholder 0.0.1s replaced by real 0.1.0 release notes drafted
   for the owner.

## 10. Out of scope

Street-address geocoding; routing or distances beyond `distance_km` on
nearest matches; a hosted API; publishing to PyPI/npm (owner's call);
renaming the npm or PyPI names; the dataset's content and rules.

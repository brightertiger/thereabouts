# Client state — 0.1.0 release draft

## Coordinate CLI — merged-tree qualification, 2026-10-05

The authorized merge of `feat/coordinate-frames` into `wp/coords-cli` is
`0dd302d` (parents `0c4be91`, `d194cd5`), with no conflicts. This section records
CLI-package validation in `thereabouts-coords-cli`; the coordinate-client report
below belongs to its earlier, separate run. All contract workspaces, placeholder
handles and obsolete snapshot runners are absent. The editable Python extension
and generated WASM were freshly built from this merged worktree against the real
`thereabouts_core::coords`, without a fallback implementation.

Scalar flags and `--point`, CSV/NDJSON/NMEA input, shared native/Node grammar,
ordered row failures, and optional query provenance are integrated. Legacy
named WGS84 reverse and H3 lookup semantics remain unchanged. Query metadata is
available without evidence; HDOP/VDOP remain dimensionless and decoded footprint
is separate from measurement accuracy. Integration edits are limited to four
owned test files and this explicitly authorized status document. Core/client
source files arrived only through the authorized merge.

### Contract drift

No landed Rust signature, public type, error variant, error code or pinned
message differs from the reproduced version-one contract. No production adapter
change was needed. The tests now compare complete query schemas and direct-core
results; Node grammar tests honor `VIRTUAL_ENV` for the required worktree-local
editable installation. No fixture, numeric tolerance or fixed vocabulary was
changed.

Two ownership issues block complete qualification. WASM scalar rendering parses
result JSON again in `core/thereabouts-wasm/src/lib.rs::render`; that parse changes
some footprint numbers before CLI-core receives them. For example, geohash
`u4pruydqqvj` has a boundary latitude of `57.649109959602356` from the WASM binding
but `57.64910995960235` after rendering. The owning clients package must resolve
this boundary. Separately, native and WASM footprint calculations differ in fields
for which fixtures do not currently declare tolerances. These are reported to
coords-core rather than silently assigning consumer-owned tolerances.

### CLI gates actually run

All builds used Rust 1.99.0, the prescribed shared target, offline/locked Cargo,
one build job, and sequential build/test processes. Logs, probes and exact
comparison outputs are under `.cache/merged-validation/`. Scratch probes link
real libraries; a pre-coordinate source copy is used only as a compatibility
baseline, never as conversion evidence.

| Gate | Actual outcome |
| --- | --- |
| `cargo fmt --check` | Passed |
| Workspace `cargo clippy --offline --locked --all-targets --all-features -- -D warnings` | Passed |
| `cargo test --offline --locked -p thereabouts-core -p thereabouts-cli-core -p thereabouts-cli -- --skip http::tests:: --test-threads=1` | 130 passed, 0 failed; 82 core and 48 CLI/CLI-core; 2 HTTP tests excluded |
| wasm32 `cargo check --offline --locked -p thereabouts-cli-core -p thereabouts-wasm` | Passed |
| Offline locked uv sync and editable `maturin develop --offline --locked --uv` | Passed, including final rebuild; both imports verified under this worktree's `clients/python/thereabouts` |
| Required pytest paths: coordinate frames, console, vectors, legacy | 30 passed, 1 failed (existing MCP tool-list assertion) |
| Final coordinate-only pytest recheck | 17 passed, 0 failed; includes all 380 shared vectors |
| Ruff check / format check and strict mypy on the new Python test | Passed; mypy checked 1 file |
| `npm ci --offline --ignore-scripts --no-audit --no-fund` | Blocked: missing cached `undici-7.30.0.tgz` |
| Real offline `npm run build` | Passed; final rebuild 20.55 s, identical WASM SHA-256 to the artifact tested |
| Ten explicit non-network Node test files, concurrency 1 | 337 passed, 107 failed: 105 footprint vector subtests, their parent, and the existing lease environment-path test |
| `npm run check` / `npm run format` | Passed |

The Python console failure is
`test_console.py::test_real_console_mcp_returns_current_result_json`: the existing
assertion lists nine tools while the merged MCP service correctly includes
`reverse_point`. That file is outside CLI ownership. The separate Node lease
failure hard-codes `.venv/bin/thereabouts`, while this worktree uses the required
`.cache/coords-venv`; `lease.test.js` is also outside ownership. Neither assertion
was skipped or changed.

Offline npm-ci failed with `ENOTCACHED` for `undici-7.30.0.tgz`. Provisional checks
used copies of the already-installed pinned undici 7.30.0, TypeScript 5.9.3 and
Prettier 3.6.2; this does not qualify npm-ci. Node 23.10.0 is the only installed
runtime found, so Node 22/24 remain unverified. Full Rust/Node suites are blocked
by the no-network rule: two Rust `http::tests` and Node `install.test.js` /
`stall.test.js` use loopback HTTP. No pipeline/importing tests, remote CI,
upstream fixture fetch, package download, publication or deployment ran.

### Shared-fixture parity and compatibility

A direct Rust probe called `coords::reverse_value` on every one of the 380
shared vectors. Python's public binding matched its full query metadata and
schema for all 380. The Python console independently matched the real binding
for all 380. Node binding and CLI each matched direct Rust on all 380 normalized
points (fixture-owned tolerances), conversion lists, error codes, status and
schema. CLI provenance remains last in the existing top-level field order.

The stricter full-footprint comparison remains blocked: direct Node/WASM differs
from native Rust on 203 vectors, all in footprint radii/vertices without declared
tolerances. The CLI differs from native Rust on 210 vectors; comparing CLI with
its own WASM binding isolates 105 affected vectors. These differences do not
change normalized query points, conversions, errors or statuses. They still fail
the added exact checks; the gate is not reported as passing. Detailed paths and
values are retained in `node-direct.json` and `node-tests-final.log`.

A fresh pre-coordinate baseline from local commit `4efb85d` produced identical
bytes to this merged tree for **340 typed reverse/H3 API results** and **1,408 CLI
outputs per runtime**, independently in native Rust and Node/WASM. API comparisons
cover the Rust-admitted numeric/string request shapes; eight transport-only invalid
requests are covered by CLI comparisons and existing client tests. CLI comparisons
include both fixture packs, evidence on/off, JSON/NDJSON/CSV/table, legacy CSV and
NDJSON batches, exit codes and stderr. No network or old binary was used as current
conversion evidence.

The shared target reused baseline libraries on an initial final Rust rerun despite
the different worktree sources. Forced compilation flags alone did not refresh the
required feature variants. Refreshing only the mtimes of the merged core and
CLI-core `src/lib.rs` forced ordinary Cargo recompilation. This is one metadata-only
ownership exception for `core/thereabouts-core/src/lib.rs`; its bytes/hash are
unchanged, recorded in `mtime-refresh.json`. No shared target cleanup, second target
or core source edit occurred. Formatting, Clippy, wasm32 check and the permitted
Rust tests then passed. The final normal-profile WASM rebuild exactly reproduced
the already-tested artifact.

Independent publication/authentication, MGRS lettering, upstream OLC and surveyed
station/epoch gaps remain as listed by the core-owned
[fixture reference record](../../tests/fixtures/coordinates/README.md).
Consumer parity does not close those reference gates.

### CLI artifact and environment measurements

Both builds used Rust/cargo 1.99.0 and wasm-bindgen 0.2.129. gzip is level 9,
mtime zero. Payload includes runtime/bin/pkg, declarations, Node README,
package.json and the root licence, excluding node_modules and tar headers; no
npm pack ran. Before is the fresh `4efb85d` build, not an inferred size.

| Bytes | Before | Merged CLI tree |
| --- | ---: | ---: |
| Generated WASM raw | 2,535,600 | 2,748,539 |
| Generated WASM gzip | 877,775 | 954,488 |
| Node source payload | 65,593 | 73,949 |
| Node payload including pkg | 2,640,902 | 2,863,871 |

The editable extension is 57,490,448 bytes. Python is 3.12.8; Node is
23.10.0. Final measured free disk is 37,562,056,704 bytes
(34.98 GiB), above the 5 GiB floor. Generated artifacts remain local/ignored.

Only the explicitly authorized merge was committed. The integration test and
status-document changes remain uncommitted; nothing was pushed, tagged,
published, deployed or merged onward.

## Coordinate clients — merged-tree qualification, 2026-10-05

Merged `feat/coordinate-frames` into `wp/coords-clients` with the authorized merge
commit `142944a` (parents `781ee87`, `53461f6`), without conflicts. The native Rust
coordinate module and all 380 shared vectors now live in this worktree. Removed
the contract-only workspace, prior real-core snapshot, Python import placeholder,
and Node fake geocoder/build-tool facades. Node adapter tests now open real WASM
geocoders. A new MCP test exercises every shared vector. No fallback conversion
implementation is shipped; all coordinate maths and domain validation remain in
`thereabouts_core::coords`.

Python scalar/stream/numeric-column APIs, PyO3/WASM bindings, Node scalar/stream
APIs and discriminated types, strict read-only MCP `reverse_point`, immutable
query metadata, and the `CARGO_TARGET_DIR` build fix are integrated. Default
named WGS84 reverse, legacy result keys, H3 ancestor lookup and `result.Point`
semantics remain unchanged. Input provenance and uncertainty are available
without evidence; decoded extent remains separate from measurement accuracy.
See [coordinate inputs](coordinates.md) and [offline builds](release.md).

### Contract drift

None found in the landed Rust signatures, public types, error variants, error
codes or pinned diagnostics. No binding production changes were required after
the merge. MCP intentionally rejects transport shapes before calling Rust; this
is the original contract, not drift. The fixed vocabulary remains unchanged:
cell precision is reported as extent, not measurement uncertainty, and frames
are explicit. The absent planning-worktree paths were previously reported;
implementation used the reproduced version-one contract.

### Gates actually run on the merged tree

All Cargo gates used Rust 1.99.0, offline/locked modes, one build job and the
prescribed shared target. Local commands were sequential; the first Rust build
waited for an active sibling build. Logs and a direct-core oracle are retained
under `.cache/coords-integration/`.

| Gate | Actual outcome |
| --- | --- |
| `cargo fmt --check` | Passed |
| Workspace `cargo clippy --offline --locked --all-targets --all-features -- -D warnings` | Passed |
| `cargo test --offline --locked -p thereabouts-core -p thereabouts-py -p thereabouts-wasm` | 82 core tests passed, 0 failures; WASM has 0 native tests; PyO3 disables Rust test/doctest harnesses |
| wasm32 check: core, CLI-core, WASM | Passed |
| Offline locked uv sync and `maturin develop --offline --locked --uv` | Passed in this worktree's `.cache/coords-venv`; inherited CONDA_PREFIX unset |
| Editable import verification | Both Python package and freshly built `_core.abi3.so` resolve under this worktree's `clients/python/thereabouts` |
| `pytest tests/client/core tests/client/mcp` | 156 passed, 0 failed |
| `pytest tests/client/cli/test_vectors.py tests/client/cli/test_legacy.py` | 10 passed, 0 failed; current CLI golden JSON and legacy mappings |
| Ruff check / format check on touched Python | Passed |
| Strict mypy on clients/python and coordinate/MCP tests | Passed: 19 files |
| `npm ci --offline --ignore-scripts --no-audit --no-fund` | Blocked: `ENOTCACHED`, missing `undici-7.30.0.tgz` |
| Real offline `npm run build` | Passed; script used the prescribed target for Cargo and wasm-bindgen |
| Non-network Node tests, nine explicit files, concurrency 1 | Initial root run: 53 passed, 5 environment failures; all four coordinate tests passed |
| Native-comparison Node recheck with real environment alias under `.cache` | 7 passed, 0 failed, including all five initially blocked tests; 58 distinct non-network tests passed across both runs |
| `npm run check` / `npm run format` | Passed |

Node used the already-installed matching undici 7.30.0, TypeScript 5.9.3 and
Prettier 3.6.2 through local ignored links/PATH; this does not qualify npm-ci.
The five Node failures are existing native-comparison tests in `grammar.test.js`
(four) and `lease.test.js` (one), which hard-code `.venv/bin/thereabouts` and
receive an absent-executable result. The required editable installation instead
lives in `.cache/coords-venv`. These test files are outside this package's
ownership and remain unchanged. All seven tests in those two files subsequently
passed using byte-identical copies under `.cache/coords-integration/native-node-check`,
with its `.venv` alias pointing to the actual `.cache/coords-venv` and runtime/pkg
links pointing to this merged worktree. Copy hashes are recorded beside the logs.
No facade or skipped assertion was substituted. The original root invocation
still needs its environment path fixed by the test owner; it is not reported as
a passing root-suite run. Coordinate parity explicitly uses this worktree's native Python interpreter.

The full `npm test` command was not run: `install.test.js` and `stall.test.js`
use loopback HTTP, forbidden by the no-network rule. Node 23.10.0 was the only
installed version found, so all Node results remain provisional for the supported
Node 22/24 matrix. No remote CI, cross-platform wheels, network, pipeline or
publication ran. Pipeline-importing tests, including
`tests/client/forward/test_plates.py`, were excluded from collection.

### Shared fixtures and compatibility

A scratch Rust probe linked the actual merged-tree core and existing serde_json
artifacts, without a manifest or dependency change, and called
`coords::reverse_value` directly for all 380 vectors. Every Python public result
matched that direct Rust result exactly, including normalized points, conversion
lists, error codes, status and schema. WASM matched native Python for all 380
vectors: exact schema/status/cell/codes/conversions and fixture-owned numeric
tolerances for normalized points. MCP returned identical public JSON for all
372 schema-admitted vectors and validation errors for the remaining eight.
No shared fixture or tolerance was edited. Strided/empty/bool numeric columns,
nonfinite optional numbers, bigint precision, frozen nested metadata, H3 r0/r8/r9,
backpressure, ordering and close-during-iteration tests passed.

A retained pre-coordinate WASM artifact and original runtime source supplied
the compatibility baseline only. The freshly built merged WASM produced identical
bytes for **348 legacy reverse/H3 API JSON results** and **1,392 CLI outputs**
(JSON, NDJSON, CSV and table, evidence on/off) across the two core fixture packs.
Exit codes and stderr also matched. The 10 native CLI tests above independently
validated committed golden JSON and the original legacy status mappings. No
baseline artifact was used as current coordinate-conversion evidence.

Independent reference gaps remain as recorded by
[coords-core](../../tests/fixtures/coordinates/README.md): authenticated publication
editions, independent MGRS lettering/upstream OLC tests, and a published surveyed
station with realization/epoch. Passing client parity does not close those gates.
CLI frame-input integration remains a separate package; its source was not edited.

### Measured coordinate artifact sizes

Before is the previously measured original production WASM; after is the fresh
merged-tree release build. Both used Rust/cargo 1.99.0,
wasm32-unknown-unknown, wasm-bindgen 0.2.129 and the shared target. gzip uses Python
level 9 with mtime zero. Payload sums runtime/bin/pkg files, declarations, README,
package.json and licence, excluding node_modules and tar headers. No npm pack ran.

| Bytes | Before | After (merged tree) |
| --- | ---: | ---: |
| Generated WASM raw | 2,535,600 | 2,648,112 |
| Generated WASM gzip | 877,775 | 922,714 |
| Node source payload | 65,593 | 73,593 |
| Node payload including generated pkg | 2,640,902 | 2,763,088 |

Python was CPython 3.12.8; Node was 23.10.0. Disk started at 35 GiB free and the
post-build measurement was 37,635,682,304 bytes free (35.05 GiB), above the 5 GiB
floor. No second target or target cleanup was used. Apart from the explicitly
authorized merge importing core-owned files, source edits remain in owned paths.
The merge is the only new commit; follow-up test/documentation changes are
uncommitted. Nothing was pushed, tagged, published or deployed.

## Previously recorded release baseline

The remaining sections describe earlier release work, not fresh coordinate
qualification. Their recorded gates and sizes must not be attributed to this
package run.

The baseline below was generated by tests.benchmarks.client_status from its
recorded script output and offline assertions before the coordinate work.
Earlier implementation and measurements remain in Git history and the JSON.

## Implemented and retired

One Rust core owns format 2.2, all lookups and result semantics. Python uses
PyO3 abi3-py311; Node 22/24 uses wasm-bindgen with host positioned reads.
A separate native writer uses typed Arrow batches and disk-backed staging.
Native clap dispatch and Node consume one JSON grammar through the same Rust
argument parser, help renderer and errors. They also share batch parsing,
rendering and exit policy. MCP is a thin optional Python host with one tool per verb.

Core provides reverse/H3 and city names. Postal, airports, LOCODE, phone, IP
and plates have separate packs. Forward packs pin the core catalogue and gain
canonical city/timezone detail when matching core is attached. They remain
usable alone with their own fields. Ambiguity keeps agreed flat fields;
reverse never reports ambiguity, and nearest answers carry distance bands.
Evidence is separate and lazy. Per-shard handles, bounded read spans,
decompressed-block caches and bounded fuzzy candidates support large packs.

The v1 runtime, Python pack reader, Cython source and generated C, old installer,
CLI and catalogue MCP paths, their old-only tests/benchmarks and binary fixtures
are deleted. The hand-written Node reader was removed in package 4.
Only four stable cell constants remain in thereabouts.format. The pipeline's
internal hierarchy codec now lives with the pipeline. Original conformance
JSON and synthetic Parquet inputs remain; no runtime compatibility shim exists.

## Final review fixes

H1: Node output retries short writes and EAGAIN; slow-reader tests retain the
entire enlarged info object and all 3,000 batch rows. Stream failures preserve
their IO exit policy and never suggest reinstalling a valid pack.
H2: the writer accepts empty grouped cell files, rejects empty block entries
and validates each block against its partition parent. An offline fixture
captures the reproduced MY/SG manifest inventory and its provenance.
M1-M2: interrupted transfers retain partials with an exit-2 resume instruction.
Rust and Node share an exclusive .lock PID/time lease with coordinated stale
recovery; live contention exits 2. No network port is reserved.
M3-M4: derived H3 centres retain the documented 1e-10 degree tolerance; terminal
width comes from COLUMNS or the host terminal, shrinking widest columns first.
Low: process substitution/FIFO input, in-tree npm caches, first-seen structured
field order, source-aware version hints, verified identity Range requests,
async disposal types, common store-path policy and lazy discovered families
are covered. Every command and flag has shared help/diagnostic wording.

The final pass briefly exceeded the 4 GB worktree allowance when build outputs
and pytest scratch overlapped. Those artifacts were removed immediately and
the remaining gates prune debug outputs before Python tests. Free disk stayed
above 5 GB; no real data or files outside the worktree were written.

## Pre-merge corrections

The editable cache now tracks all linked crates recursively, including CLI-core
resources; a dependency-graph regression test checks coverage. Install-lock docs
cover PID reuse and safe manual recovery. Tables measure all rows before output,
use the available terminal width without a fixed character cap and display
invalid-row hints. Temporary spooling keeps memory bounded and one header.
The release benchmark tolerates retired staging files, supports script/module
execution and writes tracked measurements only with --write. Retired build and
performance docs are labelled historical; code-pack examples use the public API.
Node reports the version from its package metadata.

## Use

Install an artifact built from this checkout. Python: Geocoder(data_dir="./store")
with reverse(lat=..., lon=...), from_h3, geocode, postal, airport, locode, phone,
ip and plate. reverse_many streams named points; reverse_columns returns
dictionary strings and numeric validity buffers. Results are frozen dataclasses.
The top-level surface is Geocoder, reverse, Result and coded error classes.

Node: await Geocoder.open({dataDir: "./store"}), async scalar verbs,
fromH3, reverseMany and close; results are frozen snake_case objects.
The installed package includes WASM and needs no compiler.
See the package READMEs and [cli.md](cli.md) for complete arguments.

The store is packs/<family>/<dataset-version> plus active.json. Discovery uses
an explicit directory, THEREABOUTS_DATA, then platform user data. Installs are
explicit, resumable, checksum-verified and atomically activated; there is no
implicit download. The release URL remains a placeholder. Use --from with a
local directory or an explicitly configured endpoint.

## Pipeline integration and the real subset proof

Main was merged with the maturin build and all pipeline dependency groups.
Main's native versions stayed unchanged: duckdb 1.5.6, pyarrow 23.0.1, h3 4.5.0,
numpy 2.3.5, shapely 2.1.2, scipy 1.16.3, regex 2026.9.29 and pyshp 2.4.2.
The read-only real-workspace plan reported zero stale in its labelled simulated
adoption/handover mode. This verifies mapping/hashes, not engine equivalence;
no ledger migration was applied.

The runner now passes core_pack, orders forward units after core, and creates
deterministic ustar archives and a final index unit. The standalone release
packs command schedules only the verified prepared dataset and local pack units.
The regular publication inventory includes those archives and index.

The read-only MY/SG preparation selected three r3 blocks and produced
8,802,046 dataset bytes in 14.607 s.
Packing took 3.598 s and local installation
1.323 s. Peak sampled child-tree RSS was
439,451,648 bytes.
The measurement run used 91,926,416 output bytes.
All 8 CLI checks matched: two reverse locations, city name,
postal, airport, LOCODE, phone and IP. Its phone-prefix table is empty, so phone
correctly uses country-only metadata. Null timezone detail remains explicit.

| MY/SG family | Pack bytes | Archive bytes |
| --- | ---: | ---: |
| core | 13,136,114 | 13,148,160 |
| postal | 3,045,540 | 3,061,760 |
| airports | 2,812,952 | 2,826,240 |
| locode | 2,817,278 | 2,836,480 |
| phone | 2,810,546 | 2,826,240 |
| ip | 3,037,725 | 3,051,520 |

Plates could not be built from this real snapshot: golden has no plate tables
and normalized/plates_country is absent. Core plus five forward packs were
verified, not seven packs. No fabricated or empty substitute was produced.
The existing plate sample and all plate vectors still pass.
The proof outputs are scratch; results, input hashes and pack-manifest hashes
are retained in
[CLIENT_RELEASE_MEASUREMENTS.json](../../tests/benchmarks/measurements/CLIENT_RELEASE_MEASUREMENTS.json).
Reproduce with tests.benchmarks.release_path and a new worktree-local output directory.

## Conformance and qualification

| Legacy family | Requests | Asserted mapping |
| --- | ---: | --- |
| reverse | 35 | 19 matched, 1 unassigned, 4 ineligible, 2 outside_coverage, 8 invalid_input, 1 coarse_cell_intended_change |
| postal | 8 | 4 matched, 1 ambiguous, 1 not_found, 2 invalid_input |
| airports | 11 | 2 ambiguous, 7 matched, 1 not_found, 1 invalid_input |

These are explicit mappings of the original expectations, with a short reviewed
allow-list; they are not claims that 54 old JSON objects are unchanged.
The independent golden-cells extract check runs without the real dataset.
Current and synthetic vectors total 478;
Node library and bin coverage includes typed/NUL boundary exceptions documented
in cli.md. Python and Rust assert the same files and legacy mappings.

Latest completed gate: 104 Rust tests; 510 pytest
passed, 2 skipped; mypy 465 files;
63 Node tests on 22.
Node 24: 63 tests.
Rust fmt, clippy all targets/all features with warnings denied, core/CLI-core/WASM
target checks, ruff, ruff format, mypy, npm build and TypeScript check passed.
Fresh installed-package import/version and artifact checks are documented in
[release.md](release.md). CI workflows have not been run remotely.

## Recorded performance and sizes

Apple M2, 8 GB. Python and format measurements are retained from the accepted
format pass; Node figures below were regenerated after the final review fixes.
Python hot median/p99: 7.750/9.584 µs;
random: 4.584/14.291 µs.
Columnar throughput: 636,292 hot and
772,448 random points/s.
Multishard p99: 13.625 µs; single-large-shard p99:
12.291 µs. Full workloads, cache conditions, million-key
fuzzy timings and historical comparisons remain in CLIENT_CORE_MEASUREMENTS.json.

| Node verb | Median / p99 µs | Batch results/s |
| --- | ---: | ---: |
| reverse | 6.292 / 8.792 | 148,988 |
| postal | 8.750 / 10.959 | 92,101 |
| airport | 8.625 / 10.000 | 109,619 |
| locode | 8.542 / 9.125 | 117,447 |
| phone | 10.458 / 11.083 | 138,728 |
| ip | 8.042 / 8.708 | 124,270 |
| plate | 4.792 / 5.917 | 157,747 |
| geocode | 8.208 / 10.167 | 104,352 |

Forward batch measurements are ordered scalar loops; reverse uses reverseMany.
The reproducibly built WASM is 2,539,196 bytes, not committed.
Process-start measurements, including npx overhead, remain in the same JSON.

Core sample bytes, including the forward catalogue closure:
14,740,365. Sample geography is Benelux plus
the Paris, Istanbul, Mumbai, Delhi and Springfield blocks.

| Family | Sample bytes | Estimated world bytes |
| --- | ---: | ---: |
| postal | 445,935 | 74,990,618 |
| airports | 134,628 | 3,808,534 |
| locode | 148,371 | 4,392,835 |
| phone | 66,126 | 6,111,549 |
| ip | 115,492 | 100,098,143 |
| plates | 43,463 | 3,095,294 |

World estimates use sample data bytes per row plus measured historical metadata;
they exclude manifests, notices, unmeasured supporting-table growth and shared core.
They are estimates. Previously authorized real exports measured IP
94,643,648 bytes and postal
134,347,594 bytes
on the older writer; those outputs were deleted. No new world export was run.

## Release state and owner decisions

Python and npm versions are 0.1.0. Workflows build abi3 wheels for Linux x86_64
and aarch64, macOS x86_64 and arm64, Windows x86_64, sdist and npm artifacts.
Separate pipeline CI uses synthetic inputs. Publishing requires a manual run
on a matching tag plus configured release-environment approval/trusted publishers.
The owner must configure those protections before using the jobs.

The code is MIT licensed (LICENSE); docs/licenses.md records the decision
and the separate ODbL/source-notice obligations. Registry 0.0.1 placeholders have
not been replaced. Public release hosting, real names-table
adoption, real plate tables and remote/cross-platform wheel execution remain
unverified or pending. The current names index uses canonical city names;
alternate-name support has synthetic conformance coverage.

All work stayed in this worktree. Real data was read only, tests used local
inputs/loopback, and no push, upload or publication was performed.

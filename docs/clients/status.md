# Client state — 0.1.0 release draft

## Coordinate clients — 2026-10-05 qualification

Implemented in `wp/coords-clients`: explicit Python scalar/stream/numeric-column
APIs, PyO3/WASM adapters, Node scalar/stream APIs and discriminated declarations,
strict read-only MCP `reverse_point`, frozen query metadata, and the
`CARGO_TARGET_DIR` build-script correction. All coordinate maths remains in
`thereabouts_core::coords`; legacy APIs and `result.Point` are unchanged. See
[coordinate inputs](coordinates.md) and the [offline build recipe](release.md).

**Integration is blocked in this worktree.** Its production core still lacks
`pub mod coords` and `tests/fixtures/coordinates/vectors.json`. Those files are
owned by coords-core and were not edited/copied into production here. The two
planning-worktree document paths no longer exist; the frozen design in this
checkout and `thereabouts-work/reports/coords-plan-notes.md` supplied the same
contract. No planning/vocabulary file was edited.

| Gate actually run | Outcome |
| --- | --- |
| `cargo fmt --check` from core | Passed |
| Required clippy, WASM cargo test, wasm32 cargo check | Blocked: unresolved `thereabouts_core::coords` in production core |
| `cargo test --offline --locked -p thereabouts-py` | Exit 0; this crate has no Rust test/doctest harness, so this is not extension validation |
| Offline uv sync into `.cache/coords-venv` | Passed; CPython 3.12.8, cached dependencies only |
| Normal offline `maturin develop --locked --uv` | Blocked by missing production core module; inherited CONDA_PREFIX also required unsetting |
| Root `pytest tests/client/core tests/client/mcp` | 154 passed, 1 failed: missing core-owned `coordinates/vectors.json`; using an earlier locally built real-core snapshot |
| Ruff check/format on touched Python; strict mypy | Passed; mypy checked 19 files including new tests |
| `npm ci --offline --ignore-scripts --no-audit --no-fund` | Blocked: `ENOTCACHED` for `undici-7.30.0.tgz` |
| `npm run check`, `npm run format` | Passed using already-installed TypeScript 5.9.3 / Prettier 3.6.2 via PATH; this does not establish npm-ci success |
| Python adapter/schema-only tests with test-local import placeholder | 51 passed; not native conversion evidence |
| Initial contract-only scratch clippy | Passed after binding fixes; stub bodies were never used as conversion evidence |

For provisional integration, `.cache/coords-real` contains a byte-recorded copy
of the sibling core's real Rust implementation and its then-current 380 vectors,
plus these client bindings. It retains the existing manifests, lockfile and path
dependencies. An offline maturin develop built a fresh native extension from
that copy into this worktree's own editable environment; both import paths were
verified here (`clients/python/thereabouts`, including `_core.abi3.so`). No
extension from another checkout was reused. The test-local import placeholder
was absent during every native test. Snapshot source/fixture hashes and logs
are retained in `.cache/coords-results/real-snapshot.json` and adjacent logs.

The refreshed real snapshot passed **155 core/MCP tests**, including all 380
shared vectors at their recorded tolerances. Longitude comparisons use the
core fixture runner's wrapped angular difference; no tolerance or fixture was
changed. H3 cases compare with the legacy `from_h3` path at their original
resolutions. The fresh WASM snapshot passed **13 non-network Node tests**
(`coordinates.test.js` and `library.test.js`), including native-Python
schema/status/cell/error and normalized-value parity across all 380 vectors.
The build-script facade checks both absolute and relative target paths against
the same shared target; it builds no second target tree. Final TypeScript checks
also reject mixed component sets when the default frame is omitted.

These results qualify only the recorded snapshot, not a combined production
source tree. At the final audit the original sibling worktree path was no
longer present; the tested copy and its hashes remain in this worktree's cache.
The production Rust gates, fresh editable build, Python suite and WASM checks
must run again after coordinated integration of the final core and CLI packages.
CLI source was not changed by this package. Shared-reference authority gaps remain with coords-core: the
snapshot records unauthenticated publication/edition and missing independent
MGRS/OLC oracle evidence; client tests do not promote these to verified sources.

Full `npm test` was not run: npm provisioning is blocked and the suite includes
loopback HTTP, forbidden by this task's no-network constraint. Only Node
**23.10.0** was available; no Node 22/24 matrix, remote CI, cross-platform wheel,
publication or deployment was run. Python tests were limited to core/MCP;
`tests/client/forward/test_plates.py` and all pipeline tests were excluded.
No conversion dependency was installed. No new vocabulary defect was found;
the documented explicit-label and geodetic-pole-origin caveats remain in force.

### Measured coordinate artifact sizes

Both builds used Rust/cargo 1.99.0, wasm32-unknown-unknown release mode,
wasm-bindgen 0.2.129 and one Cargo job on the prescribed shared target. Before:
original production sources. After: the recorded real-core snapshot with these
bindings. gzip is Python gzip level 9 with mtime zero. Payload is the sum of the
Node whitelist's runtime/bin/pkg files, declarations, README, package.json and
licence; it excludes node_modules and tar headers. No npm pack/publish occurred.

| Bytes | Before | After (provisional real snapshot) |
| --- | ---: | ---: |
| Generated WASM raw | 2,535,600 | 2,650,099 |
| Generated WASM gzip | 877,775 | 923,595 |
| Node source payload | 65,593 | 73,593 |
| Node payload including generated pkg | 2,640,902 | 2,765,075 |

Disk started at 38 GiB free and remained above the 5 GiB floor; the final check
reported 35 GiB free. No shared-target cleanup or second target was used. All
source changes are within the package's owned paths. Scratch, environment and
snapshot outputs are local/ignored. Changes are uncommitted; nothing was
pushed, tagged, published, deployed or merged.

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

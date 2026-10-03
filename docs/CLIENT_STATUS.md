# Thereabouts client status

Work package 1 implements the shared Rust core and the new Python reverse API.
It is local work on `feat/rust-core`, based on `3ade5da`. No package 2 work,
remote push, pull request, merge or publication is included.

## Rework progress

Review fix 1 separates the writer from the runtime. The portable core passes
`cargo check -p thereabouts-core --target wasm32-unknown-unknown`; its normal
dependencies are h3o, serde, serde_json, sha2 and thiserror, with no `*-sys` crates.
Review fix 2 makes opening lazy: headers and block directories are read first,
with 8 MiB decoded-block and 16 MiB raw-catalogue LRU caches. Pass
`verify=True` to the Python constructor for full verification at open.
Review fix 3 removes non-test expect calls and denies unwrap/expect in Clippy.
The indexing warning is enabled; narrow allowances document validated wire
spans, fixed schema arrays and serde_json reads that return null.
Review fixes 4–5 keep timezone overlap in evidence without changing reverse
status, narrow zones by country, remove selected, and replace distance_km with
a published distance_band. Reverse candidates are always empty.
Review fix 6 requires all eight input table kinds and explicit distance policy,
rejects invalid populations, and enriches the synthetic Parquet fixture with
country/subdivision metadata and overlapping timezone rows.
Review fix 7 asserts all 35 legacy reverse requests against their original
expectations in Rust and Python, with only two declared migrations: accepting
case 47 at r3 and using the canonical city name. A committed source extract
makes the independent golden comparison part of offline pytest.
Review fix 8 distinguishes absent explicit paths (pack_not_found), missing
store data and writer inputs. Stale-stage messages name the cleanup path;
cleanup failures no longer hide the original export error.
Review fix 9 makes result status/kind/match Rust enums and indexes country,
subdivision and zone membership metadata. State fields use the subdivision
row for the place code, falling back only when that row is absent.
Review fix 10 constructs scalar dictionaries directly and streams native
results into fixed-width/dictionary buffers. A 4 MiB decoded-place LRU avoids
repeated validation for hot places while retaining bounded memory. The random
workload exposes catalogue-cache misses and has lower throughput than eager
reading; that tradeoff is measured below.
Review fix 11 reads typed Arrow arrays, caches repeated SQL statements and
inserts bounded batches within one transaction. staging_directory controls
SQLite and output staging without entering pack identity. Preflight preserves
a 5 GiB floor plus an input-size estimate; no world build was run. Typed reads
preserve Parquet floating-point values without the old JSON intermediate;
the encoder revision records that byte-level correction.
Remaining review fixes are in progress.

## Built and usable

`core/` is an edition-2024 workspace with MSRV Rust 1.99. `thereabouts-core`
owns format-2 containers, checksums, catalogue records and reverse lookup.
The separate `thereabouts-writer` owns Parquet export and timezone joins; its
native Arrow/SQLite dependencies never enter the portable core. The Python
writer feature is optional in Cargo and enabled in maturin builds. `thereabouts-py` exposes an `abi3-py311` extension via
maturin. No application Rust code uses unsafe or non-test `unwrap()` calls.

The public exports are `Geocoder`, `reverse`, `Result`, `GeocoderError`,
`DataNotInstalledError`, `IncompatibleDataError`, `CorruptPackError` and
`ClosedGeocoderError`. Every public error has a stable `code`. Missing-data
messages give exactly `thereabouts data install core`; installation itself
remains work package 3. Queries never download anything.

```python
import numpy as np
from thereabouts import Geocoder

with Geocoder("tests/fixtures/packs/core-sample") as geo:
    answer = geo.reverse(lat=50.8503, lon=4.3517)
    print(answer.country.code, answer.city.name, answer.timezone, answer.match)
    print(answer.to_dict())
    audit = geo.reverse(lat=50.8503, lon=4.3517, evidence=True)
    cell = geo.from_h3("881fa44181fffff")
    rows = list(geo.reverse_many([(50.8503, 4.3517), (52.3676, 4.9041)]))
    columns = geo.reverse_columns(
        np.array([50.8503, 52.3676]), np.array([4.3517, 4.9041])
    )
```

Results and their nested objects are frozen, detached dataclasses. Not-found
and invalid coordinates/H3 inputs are statuses. Scalar coordinates are keyword
only. H3 resolutions 0–8 are admitted; 0–2 cannot have a stored ancestor and
return not-found. Coarse queries do not pick a descendant's geographic label.

`reverse_many` streams in input order. `reverse_columns` accepts numeric 1-D
NumPy arrays, including strided arrays, and returns NumPy arrays. It copies
inputs before releasing the GIL, so concurrent input mutation cannot invalidate
borrowed buffers. Rust fills fixed-width buffers one row at a time outside the
GIL. Strings are dictionary encoded: `<column>` is int32, with null code -1,
and `<column>_categories` is an array of unique strings in first-use order.
Numeric columns retain `<column>_valid` masks. Coordinates and both distance
band bounds use float64; city_population uses uint32. Categories have their
own length, so only row buffers and validity masks match the input length.
Candidates are absent from column output because reverse never produces them.
Scalar dictionaries are built directly from the Rust result. Evidence is opt-in.

For Arrow, use `pa.DictionaryArray.from_arrays(pa.array(codes, mask=codes < 0),
pa.array(categories))`. Numeric arrays use their explicit validity masks.

Discovery reuses `packs/<family>/v-<version>/<manifest_sha256>/` and
`packs/<family>/current.json`. Explicit `data_dir` takes precedence over
`THEREABOUTS_DATA`, then the existing platform user-data location. A legacy
reverse installation is discovered and reported as incompatible with format 2.
The module-level `reverse` shortcut lazily opens and reuses the default handle.

The extension also exposes `open`, `write_pack`, `verify_pack`, and `pack_info`.
`write_pack` accepts a completed golden/dataset manifest and explicit options;
see [PACK_FORMAT.md](PACK_FORMAT.md) and [the sample builder](../tools/build_sample_pack.py).
Its disk-backed place joins and block-local timezone joins avoid a world-sized
in-memory build index. Full verification visits one shard at a time. Runtime
opening retains only directories and metadata; blocks and catalogue payloads
are validated on demand. World runtime memory is not qualified. The writer admission budget is 512 MiB, not a proven RSS ceiling.

## Format and retained compatibility

[PACK_FORMAT.md](PACK_FORMAT.md) is the normative format-2 specification.
Resolution-3 directories and sparse resolution-3–8 keys remain. Labels grow
from 16 to 20 bytes with a timezone-set reference; catalogue records grow from
64 to 80 bytes with microdegree coordinates, population and a timezone string
reference. New metadata holds countries, subdivisions and IANA zone tables.
Timezone joins may split geographic ancestors. Overlap is narrowed by country;
a single survivor is timezone, otherwise the sorted list is evidence.timezones.
Overlap never makes a reverse result ambiguous. There is no selected field.

Canonical-city names, kind, point and population come from `canonical_cities`;
rural places remain the golden final settlement. The old synthetic fixture's
canonical name differs from its place display name, so the new frozen vectors
use the canonical name while checking old identities and methods independently.

The old APIs remain at `thereabouts.api` and `thereabouts.client`; their models
are preserved in `models.py` and renamed `client_results.py`. Existing tests now
import those explicit modules instead of the changed public exports. The old
CLI, installer, MCP, Python readers and Node reader remain on their existing
formats. `build_data/` is unchanged. Setuptools/Cython extension building and
its cibuildwheel configuration are removed; generated C/PYX sources remain
until package 5. The old reader passes using its Python backend.

## Committed sample and conformance

The real sample has **4,498,416 bytes** across **29 blocks**, with dataset label
`2026.10` assigned explicitly by the sample builder. Its original golden manifest
SHA-256 is `e00247767ed54c5181b5a0bc34cdb8bc3932ec943dfa82c13e8160bec4ee6832`.
Every consumed original input digest and the subset definition are retained in
the pack manifest. The original source notices are included.

Coverage is continental Belgium, Netherlands and Luxembourg, plus full r3
blocks containing Paris, Istanbul, Mumbai, Delhi and Springfield, Illinois.
One additional Montana block (`832791fffffffff`) supplies distant-nearest rows;
none of the originally requested blocks had that method. Benelux borders are
represented by retained country rows, not foreign rows from the bounding box.
Metadata is restricted to referenced subdivisions and timezone names. The first
unfiltered-metadata candidate measured 5,667,909 bytes; metadata filtering kept
the requested geography while meeting the 5 MB target.

Regenerate explicitly, reading the real dataset but writing only here:

```sh
export PATH="$HOME/.cargo/bin:$PATH"
export CARGO_HOME="$PWD/.cargo-cache" UV_CACHE_DIR="$PWD/.cache/uv" TMPDIR="$PWD/.tmp"
mkdir -p "$TMPDIR"
uv sync --all-extras
uv run python tools/build_sample_pack.py
uv run python -m tools.build_core_vectors
uv run python -m tools.check_sample_source
```

The sample build is idempotent and verifies existing output. The synthetic
Parquet fixture is committed too, allowing `cargo test` to exercise the writer
without Python or real data. There are **139 real reverse vectors** (coordinates
and H3), including every selected country, no-land/misses, distant-nearest and
overlapping timezones. Offline pytest checks all **131 resolution-8 requests**
against committed golden-cell extracts, including **123 matched requests**,
state identities/names, methods and country-narrowed timezone evidence. The
extract is generated by the read-only sample builder independently of the core.

Exactly **35 of the 54 legacy vectors** run on the new core. Direct Rust and
Python assertions compare the unchanged legacy fixture: **19 matched**, **1
unassigned → not_found/unassigned**, **4 ineligible → not_found/no_land**, **2
outside_coverage → not_found/outside_coverage**, **8 InvalidInputError →
invalid_input**, and **1 intended change** (case 47: r3 is accepted and returns
not_found/no_stored_ancestor). Matched assertions cover city ID, country code,
state ID/name and method; the sole display-name allowance is the synthetic
canonical city's name. Snapshot bundles are additional cross-language tests,
not the independent oracle. The **19 postal/airport vectors are legacy-only**
until package 2. Existing legacy tests continue to run.
Node consumption
of the new vector bundles belongs to package 4.

## Measurements and checks

[CLIENT_CORE_MEASUREMENTS.json](CLIENT_CORE_MEASUREMENTS.json) is produced only by
`uv run python -m benchmarks.core_read_path --output docs/CLIENT_CORE_MEASUREMENTS.json`.
It records the Apple M2, 8 GiB RAM, macOS arm64, Python 3.12.8, workload seed,
sample size, repetitions, latency, throughput and process peak RSS.

| New Python path, real sample | Measured result |
| --- | ---: |
| Open | 3.108 ms |
| Open RSS delta | 1,097,728 bytes |
| cache_hot scalar median / p99 | 7.417 / 8.041 µs |
| cache_hot columns | 754,774 points/s |
| random scalar median / p99 | 4.417 / 37.541 µs |
| random columns | 417,683 points/s |

Before lazy opening, the same script measured 59.041 ms
and an RSS delta of 21,872,640 bytes. The random workload
uses 100,000 coordinates rejection-sampled inside inventoried r3 blocks.
Hot throughput exceeds the eager baseline; random throughput remains below it
because catalogue records are decoded and validated on cache misses. The JSON
retains both eager and pre-binding-change measurements for comparison.

The historical reader figures are 10.291 µs scalar median / 531,994 column
rows/s for Cython and 12.750 µs / 530,437 for Python. They came from
`benchmarks.read_path` on 308,032 synthetic rows and 4,176 places. The new real
sample and richer column schema differ; these figures are context, not a
controlled speedup claim. World and cold-disk performance remain unmeasured.

Pre-commit verification passes: workspace formatting, Clippy with warnings
denied, **18 Rust tests** (unit/property/conformance/writer), **650 Python tests
passed, 9 skipped** (including the unavailable old Cython backend and world-data
checks), Ruff lint/format (**426 files**) and strict mypy (**408 source files**). PyO3 is tested from Python; its empty Rust test
harness is disabled to avoid embedding a separately discoverable libpython on
macOS. Only macOS arm64 / Python 3.12 was executed; abi3 wheels for other systems
and Python versions are not yet qualified.

## Deliberately left for subsequent packages

Package 2 adds forward families and the canonical-city FST/trigram name index;
this package stores catalogue data but does not build that index. Package 3
replaces the CLI, installer and MCP surfaces; package 4 adds WASM/Node; package 5
retires old readers and handles release engineering. No forward API stubs are
exported. Golden zone tables currently contain zone.tab metadata, not historical
UTC transitions; offset calculation needs additional data before it can be
promised. Interrupted writer staging is inspectable but does not resume.

All task artifacts, environments, caches and Cargo target output remain inside
this worktree. The real data directory was read only. Local Git commits use the
worktree's normal shared Git metadata. Nothing was pushed or published.

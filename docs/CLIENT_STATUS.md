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
borrowed buffers. Rust lookup runs outside the GIL; Python object-array creation
runs with it. Batch execution currently materializes native result rows before
column conversion; further allocation work can improve throughput.

Column names flatten nested fields (`country_code`, `city_name`, `point_lat`,
`city_point_lat`, etc.). String nulls are Python `None`; numeric columns have
explicit `<column>_valid` boolean masks. Population uses uint32 storage with
invalid zero slots, coordinates/distance use float64 with invalid NaN slots.
Consumers must use validity masks when constructing Arrow arrays. Ambiguous
rows preserve a `candidates` object column. Scalar JSON never substitutes zero
or empty strings for missing values. Evidence is opt-in; exact nearest distance
is null because the dataset publishes distance bands only.

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
Timezone joins may split geographic ancestors and retain overlapping zones as
ambiguous candidates, ordered by zone name, with `selected` null.

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
overlapping timezones. A separate source checker independently confirmed all
**123 matched r8 requests** against original golden cell identities and methods.

All **54 original vectors** still run through the legacy Python reader and CLI.
The new Rust and Python core runs the **35 reverse requests**, with explicit
status/result migration, plus the 139 real vectors. The other **19 original
vectors are postal/airport queries** and cannot execute in a reverse-only core;
they remain with their working legacy implementation until package 2. No test
has been relabelled as new-core coverage for those families. Node consumption
of the new vector bundles belongs to package 4.

## Measurements and checks

[CLIENT_CORE_MEASUREMENTS.json](CLIENT_CORE_MEASUREMENTS.json) is produced only by
`uv run python -m benchmarks.core_read_path --output docs/CLIENT_CORE_MEASUREMENTS.json`.
It records the Apple M2, 8 GiB RAM, macOS arm64, Python 3.12.8, workload seed,
sample size, repetitions, latency, throughput and process peak RSS.

| New Python path, real sample | Measured result |
| --- | ---: |
| Open | 10.102 ms |
| Open RSS delta | 1,015,808.000 bytes |
| cache_hot scalar median / p99 | 12.917 / 27.667 µs |
| cache_hot columns | 184,956 points/s |
| random scalar median / p99 | 5.542 / 14.000 µs |
| random columns | 320,130 points/s |

Before lazy opening, the same script measured 59.041 ms
and an RSS delta of 21,872,640 bytes. The random workload
uses 100,000 coordinates rejection-sampled inside inventoried r3 blocks.
Lookup throughput currently regressed because on-demand places are repeatedly
decoded and validated; review fix 10 addresses the binding allocation path.

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

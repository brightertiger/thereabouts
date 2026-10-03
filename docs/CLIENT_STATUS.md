# Thereabouts client status

Work package 1 and its review rework are complete on `feat/rust-core`.
Package 2 has not started. The approved design is
[the client redesign specification](superpowers/specs/2026-10-03-client-redesign-design.md);
[PACK_FORMAT.md](PACK_FORMAT.md) defines the version-2 wire format.

## What changed in the rework

The writer is separate from the portable reader. Opening reads inventories,
headers, directories and metadata, then validates payloads on demand with
bounded LRU caches. Panicking conversions were removed and Clippy denies
unwrap/expect outside tests. Reverse overlap never creates ambiguity:
country membership narrows timezone sets, with unresolved survivors in evidence.
The result has distance_band and no selected or distance_km.

Writer inputs now require all eight tables and explicit distance policy,
with invalid populations rejected. Legacy conformance uses original expectations;
an independent golden extract runs offline under pytest. Error codes distinguish
discovery, explicit paths, corruption and export. Typed result enums and metadata
indexes supply subdivision names from their published table. The binding builds
scalar dictionaries directly and streams dictionary-coded columns. Typed Arrow
reads, cached SQL and bounded insert batches improve the writer without a world
run. Staging has a disk precheck. Coarse queries retain their own cell, batch
coordinates are named, core discovery has no legacy-reader dependency, and
timezone compaction cannot merge above a source cell's original resolution.

## Built and usable

The Rust workspace uses edition 2024 / Rust 1.99. `thereabouts-core` contains
format codecs, lazy reading, reverse lookup and the typed result model.
`thereabouts-writer` owns Arrow/Parquet and SQLite, behind the Python crate's
optional `writer` feature (enabled by maturin). The portable core's normal
direct dependencies are h3o 0.9.5, serde 1.0.229, serde_json 1.0.151, sha2 0.10.9
and thiserror 2.0.21. Its normal dependency tree has no `*-sys` crates and
`cargo check -p thereabouts-core --target wasm32-unknown-unknown` passes.

The top-level Python API exports `Geocoder`, `reverse`, `Result`, and the
current error classes: `GeocoderError`, `DataNotInstalledError`,
`PackNotFoundError`, `IncompatibleDataError`, `CorruptPackError`,
`ClosedGeocoderError`, `WriterError` and `WriterInputError`.

```python
import numpy as np
from thereabouts import Geocoder

with Geocoder("tests/fixtures/packs/core-sample") as geo:
    answer = geo.reverse(lat=50.8503, lon=4.3517, evidence=True)
    cell = geo.from_h3("881fa44181fffff")
    rows = list(geo.reverse_many([
        {"lat": 50.8503, "lon": 4.3517},
        {"lat": 52.3676, "lon": 4.9041},
    ]))
    columns = geo.reverse_columns(
        np.array([50.8503, 52.3676]), np.array([4.3517, 4.9041])
    )
```

Results and nested values are frozen, detached dataclasses. Coordinate arguments
are keyword-only. reverse_many accepts mappings with lat/lon keys or objects
with those attributes; bare tuples are rejected. H3 resolutions 0–8 are admitted;
0–2 have no stored ancestor and return not_found. Coarse queries return their
own cell and centre, without choosing a descendant label. Reverse statuses are
matched, not_found and invalid_input. Forward ambiguity remains for package 2.

Contained results have null distance_band. Nearest results report
greater_than_km=0 and at_most_km=25 for this dataset; distant-nearest uses
greater_than_km=25 and at_most_km=50. These are published policy bounds for
represented cell centres, not measured distances to a city centroid.
State code/name come from the matching subdivision row, falling back to the
place only when no row exists. Evidence includes stored cell, source geography
IDs, assignment methods, miss reason, source IDs and unresolved timezone names.

Column strings use int32 codes and a `<field>_categories` string array.
Code -1 means null; categories have their own length and contain no null.
Numeric fields use `<field>_valid` masks (float64 for coordinates/band bounds,
uint32 for population). Column output omits candidates and evidence. It copies
strided inputs before releasing the GIL and fills fixed-width buffers without
retaining result rows. Arrow conversion is
`pa.DictionaryArray.from_arrays(pa.array(codes, mask=codes < 0), pa.array(categories))`.

`Geocoder()` and the lazy module-level reverse shortcut discover the existing
`packs/core/v-<version>/<manifest_sha256>/` layout and current.json pointer.
Explicit data_dir precedes THEREABOUTS_DATA and the platform user-data directory.
A legacy reverse pointer raises the current IncompatibleDataError directly.
Missing discovery data says exactly `thereabouts data install core`; the new
installer/CLI belongs to package 3. A missing explicit pack includes its path
and uses pack_not_found. Queries never download anything.

Default open validates directories and sizes. `Geocoder(path, verify=True)`
or `_core.verify_pack(path)` checks all hashes and structural invariants.
Unused payload damage may remain undetected during a default open. Retained
cache budgets are 8 MiB decoded blocks, 16 MiB raw catalogue shards and 4 MiB
decoded places; active readers can temporarily retain evicted values.
The pack directory must remain available and immutable while open.

## Writer and samples

`_core.write_pack(dataset_dir, "core", output_dir, options)` requires an explicit
data_version and these inventory kinds: cells, places, canonical_cities,
place_to_city, countries, subdivisions, timezone_cells and zone_tables.
Deliberate fixture omissions must be listed in allow_missing_tables. Both
normalization.policy distance bounds are required; population is null or a
nonnegative u32 integer. Writer inputs raise a coded ValueError subclass.

The 512 MiB admission budget covers bounded Arrow scans, block-local timezone
joins, output shards and a 16 MiB SQLite cache; it is not a proven world RSS
limit. Inserts are capped by rows and payload bytes inside the transaction.
staging_directory chooses the parent of output staging and SQLite on the same
filesystem; it is excluded from pack identity. Preflight requires a 5 GiB floor
plus eight times consumed compressed input size and a 64 MiB shard reserve.
The estimate is not a world-build guarantee. Existing output is verified and
reused only for the same input identity; changed inputs are never overwritten.
Stale-stage errors name the directory to remove; cleanup preserves the original
failure. Encoding revision changes when emitted bytes change.

The committed real sample is **4,498,635 bytes**, **29 resolution-3
blocks**, dataset label **2026.10**. It covers continental Belgium, Netherlands
and Luxembourg, plus Paris, Istanbul, Mumbai, Delhi, Springfield (Illinois)
and one Montana block supplying distant-nearest examples. Source notices and
original input digests are retained. The golden manifest SHA-256 is
`e00247767ed54c5181b5a0bc34cdb8bc3932ec943dfa82c13e8160bec4ee6832`.

The builder requires --golden, pins Parquet settings and records PyArrow's
version. Byte-identical subset regeneration requires that version; input
identity changes if the subset encoding changes. It reads the source only
and writes inside this worktree:

```sh
export PATH="$HOME/.cargo/bin:$PATH"
export CARGO_HOME="$PWD/.cargo-cache" UV_CACHE_DIR="$PWD/.cache/uv" TMPDIR="$PWD/.tmp"
uv sync --all-extras
uv run python -m tools.build_sample_pack --golden /path/to/data/golden
uv run python -m tools.build_core_vectors
uv run python -m tools.check_sample_source
```

The synthetic Parquet dataset includes all eight kinds and overlapping zones.
Both packs exercise writer determinism. Rebuilding a changed fixture requires
moving its previous pack aside explicitly; the writer does not overwrite it.

## Conformance

Exactly **35 of 54 legacy vectors** run against original expectations in Rust,
pytest and the vector builder: **19 matches**, **1 unassigned → not_found with
unassigned**, **4 ineligible → not_found with no_land**, **2 outside_coverage →
not_found with outside_coverage**, **8 InvalidInputError → invalid_input**, and
**1 intended change** (case 47 accepts r3 and returns no_stored_ancestor).
The only other allow-list entry is the synthetic canonical city's display name.
Matched assertions cover city/country/state IDs, country code, state name and
method. The **19 postal/airport vectors remain legacy-only** until package 2.

There are **139 real reverse vectors** shared by Rust and Python. Their snapshot
results supplement the independent oracle: offline pytest checks **131 r8
requests**, including **123 matches**, against committed golden-cell extracts,
source state fields, timezone rows and original stored-cell ancestry.
No real-data directory is needed for tests. The old reader and CLI suites still
run unchanged in scope. Node consumption awaits its binding package.

## Measurements and verification

Only [benchmarks/core_read_path.py](../benchmarks/core_read_path.py) produces the
figures below, recorded in [CLIENT_CORE_MEASUREMENTS.json](CLIENT_CORE_MEASUREMENTS.json).
Machine: Apple M2, 8 GiB, macOS arm64, Python 3.12.8. The hot workload samples
65 coordinate vectors for 20,000 calls. Random uses 100,000 seeded coordinates
rejection-sampled inside inventoried r3 blocks. Batches repeat seven times.

| Measure | Eager baseline before rework | Reworked reader |
| --- | ---: | ---: |
| Open | 59.041 ms | 2.950 ms |
| Open RSS delta | 21,872,640 bytes | 1,048,576 bytes |
| Hot scalar median / p99 | 8.833 / 22.917 µs | 7.584 / 8.250 µs |
| Hot columns | 553,973 points/s | 763,474 points/s |
| Random scalar median / p99 | 5.500 / 9.833 µs | 4.417 / 36.333 µs |
| Random columns | 665,566 points/s | 426,341 points/s |
| Process peak RSS | 300,318,720 bytes | 140,132,352 bytes |

The eager baseline retains all decoded records and used the pre-correction
result semantics. Random throughput is lower with bounded catalogue caching;
cache misses decode and validate records on demand. Hot lookup and opening
improve, and batch memory use falls. The JSON also retains measurements taken
immediately after lazy opening, before the binding optimization.

Historical old-reader figures in the script are **10.291 µs / 531,994 points/s**
for Cython and **12.750 µs / 530,437 points/s** for Python. Those used a different
synthetic dataset (308,032 cells / 4,176 places), so they are context rather than
a controlled comparison with this real sample.

Required gates are cargo fmt --check, cargo clippy --all-targets -- -D warnings,
cargo test, pytest, ruff check, ruff format --check and strict mypy. Additional
checks cover the wasm target and Clippy with all features. All passed at the
end of the rework: 28 Rust tests, 667 Python tests (9 skipped), and mypy over
419 source files. Property tests
include invalid payloads with recomputed checksums, verified open, full verify
and lazy access without panics. No application Rust unsafe is used.

## Deliberately not done and unverified

Package 2 forward families and the names index have not started. The new CLI,
installer, MCP wiring and Node/WASM host adapter remain later packages.
Legacy modules, their helper implementations and their tests remain importable
until package 5; core discovery imports only retained helpers. build_data is
unchanged. There is no world export or world performance qualification.
Linux, Windows and other Python versions were not run; wasm was compile-checked.
Disk use stayed inside the worktree with more than 5 GiB free. Real data was
read-only; no source data was modified, and nothing was pushed or published.

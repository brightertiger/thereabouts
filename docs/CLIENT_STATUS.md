# Thereabouts client status

Work package 1 and the package-2 prerequisite fixes are complete on `feat/rust-core`.
Postal is implemented in package 2; airports and the remaining families follow. The approved design is
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

## Package 2 prerequisites (N1–N5 and writer fix 11)

Shards retain open descriptors and use positioned reads. Catalogue misses read
only the requested record, offset pairs and strings. Linked-key LRU operations
are O(1), with IO and decoding outside locks. Country narrowing that removes
every timezone now retains the original set. Result enums exactly follow the
specification. Writer hot scans borrow typed Arrow fields and stage typed SQL
columns; JSON remains only for published evidence and small metadata sections.
Output bytes remain deterministic against the existing synthetic pack.
SQLite scratch may use a separate filesystem. No world export was run.

`uv run python -m benchmarks.multishard_read_path --record before|after` builds
a local synthetic pack with 256 catalogue shards,
16,384 places and 36,678,465 bytes. The same seeded
100,000 random queries run before and after, with seven columnar repetitions.
On the Apple M2 / 8 GiB machine, scalar median is
18.459 → 13.209 µs, p99 is
53.166 → 107.750 µs, and columns are
39,707 → 140,439 points/s.
The range-read implementation improves median and throughput on this workload,
but its p99 is worse; it is not a claim of improved tail latency or world performance.
The benchmark pack is generated under .tmp, not committed as a large fixture.

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
cache budgets are 8 MiB decoded blocks and 4 MiB decoded places; active readers can temporarily retain evicted values.
Open shards retain their file handles and use positioned reads. Replacing paths is safe; in-place mutation of open files is unsupported.

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
staging_directory chooses the output staging parent on the same filesystem.
sqlite_directory can use a separate disk with its own admission check. Both
options are excluded from pack identity. Preflight requires a 5 GiB floor
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
method. The eight postal cases now also run against the original expectations in Rust and pytest: four matched, one ambiguous, one not_found and two invalid_input. The remaining eleven airport cases follow with that family. Code matches now say exact; the canonical-name allowance is unchanged.

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
end of the rework: 35 Rust tests, 674 Python tests (9 skipped), and mypy over
429 source files. Property tests
include invalid payloads with recomputed checksums, verified open, full verify
and lazy access without panics. No application Rust unsafe is used.

## Deliberately not done and unverified

The remaining package-2 forward families and names index follow the postal commit. The new CLI,
installer, MCP wiring and Node/WASM host adapter remain later packages.
Legacy modules, their helper implementations and their tests remain importable
until package 5; core discovery imports only retained helpers. build_data is
unchanged. There is no world export or world performance qualification.
Linux, Windows and other Python versions were not run; wasm was compile-checked.
Disk use stayed inside the worktree with more than 5 GiB free. Real data was
read-only; no source data was modified, and nothing was pushed or published.

## Postal implementation

The postal pack supplies country-scoped exact lookup, source points and published
canonical-city roll-up. Unknown codes are ordinary misses; missing country and
invalid values return invalid_input with a hint. Ambiguous flat fields are null,
with ranked candidates. Source place and administrative names remain in evidence.
A separate family pack can be opened directly with Geocoder(path), or several
can be selected using Geocoder(packs={"core": core_path, "postal": postal_path}).
All selected families must have the same dataset version. Existing store
discovery supports a postal-only installation. No installer or CLI changes are
part of this package.

geo.postal(code, country="FR", evidence=True) returns a frozen Result.
geo.postal_columns(codes, country="FR") releases the GIL and emits dictionary
strings, numeric validity masks, candidate_offsets, and candidate_ columns.
Column buffers are filled without retaining a full result per input.

The committed sample contains the first 32 distinct codes per requested country
plus named examples; every source observation of each selected code is retained.
The sample builder takes an explicit --golden path. Countries are BE, NL, LU,
FR, TR, IN and US. Independently extracted source rows and place_to_city mappings
are checked offline by pytest, including source IDs, geography and point
quantization. The synthetic pack comes from the unchanged legacy fixture builder.

Forward figures below come only from benchmarks.forward_read_path and are saved
in CLIENT_FORWARD_MEASUREMENTS.json. They use the Apple M2 / 8 GiB machine,
20,000 scalar calls and seven native batch repetitions over three matching US
codes. The world estimate multiplies total sample bytes per source row by the
published source-row count. Fixed metadata and notices make that deliberately
crude ratio strongly upward-biased; it is not a measured world pack size.

## Forward measurements

<!-- forward-measurements:start -->
| Family | Sample bytes / rows | Real vectors | Scalar median / p99 (µs) | Batch rows/s | Estimated world bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| postal | 363,327 / 897 | 28 | 7.459 / 10.375 | 474,755 | 2,039,842,937 |
| airports | 375,778 / 213 | 33 | 7.417 / 9.334 | 469,223 | 151,994,262 |
<!-- forward-measurements:end -->

## Airports

The airports pack and airport/airport_columns methods are implemented. Default
lookup combines IATA and ICAO; scheme selects IATA, ICAO, GPS, local or ident.
Local codes need a country. All schemes are checked against an independent
committed source extract; 33 real vectors and 11 synthetic vectors also run in
Rust and Python. Of the original 11 airport cases, seven remain matched, one
not_found, one invalid_input (old context error), and two are ambiguous. The
second ambiguous case is the one intended change: legacy case 52 now uses the
default IATA/ICAO search and is asserted against case 32's original candidates.
The seven matched cases retain source identity and geographic IDs; the same
explicit canonical display-name allowance as reverse applies. Together with
postal, all 19 legacy forward cases have direct assertions, not just snapshots.

The sample selects the first 32 airport identifiers per country where available,
plus CDG, AMS, BRU, LUX, IST, BOM, DEL and SPI. It includes BE, NL, LU, FR, TR, IN
and US. The writer retains all five published schemes and explicit nulls.

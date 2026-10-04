# Final H3 table evaluation — 2026-10-01

> Historical: the table measured here was the v1 `data/h3-world` export, now removed from the repository; the `benchmarks.build_size` command below no longer exists.

The accepted resolution-8 combined design and its exact-equivalence contract are
in [DESIGN.md](../DESIGN.md). These measurements use the rebuilt pack with both the
current-settlement filter and land/country eligibility rule. The previous mask
audit, experimental layouts and their reports have been removed.

## Pack and build

The reference source pack is `data/reference`; the exported table is
`data/h3-world`. Complete installed size is **53,056,366 bytes (53.06 MB)**;
a ZIP of every pack file using deflate level 9 is **21,347,383 bytes
(21.35 MB)**. Table payload alone is 50,951,071 bytes. All reported MB
are decimal. The table retains country, state and city at resolution 8.

Build plus full verification took **687.93 s**. It enumerated
**691,776,122** actual descendant centres, directly labelled
**40,319,034** unresolved leaf centres, and additionally evaluated
certificate midpoints. The combined table contains **20,808,748** stored keys.
Peak build RSS during labelling was **246.60 MB**;
this precedes full verification. Source-pack creation/download and ZIP time are
excluded from build timing. Fixture validation also ran during this build, so the
wall-clock build time includes that machine contention.

[build.json](../../benchmarks/build.json) records these measurements. Rebuild with
`uv run python -m benchmarks.build_size --reference data/reference --data data/h3-world`
after removing previous generated outputs (retain pinned `data/cache` archives).
The command creates the reference pack if absent, builds/verifies the table and
measures installed/ZIP sizes. The ZIP is temporary; no extra pack copy is retained.

## Accuracy at original input coordinates

The reference and table use identical frozen sources and ambiguity/tie policies;
the reference evaluates the original point, while the table labels its finest H3
cell centre. Each workload contains **100,000** original-point land samples.

| Workload | Country mismatches | State mismatches | City mismatches | No table row |
| --- | ---: | ---: | ---: | ---: |
| Area-uniform spherical land | 83 (0.083%) | 212 (0.212%) | 763 (0.763%) | 57 |
| Uniform eligible settlement, uniform-area 5 km disk, land only | 235 (0.235%) | 606 (0.606%) | 5,212 (5.212%) | 169 |

Rates compare public names and include missing values. They measure centre
quantization under this source policy, not municipal boundaries or independent
geographic accuracy. Nearby samples are settlement-weighted, not population-weighted;
filtering the catalogue also changes that sampling population. Seeds are 20261001
for land and 20261002 for nearby points. The fixed city cutoff is 50 km.

Run `uv run python -m benchmarks.accuracy`; [accuracy.json](../../benchmarks/accuracy.json)
records counts, policy, seeds and both manifest hashes. The sampler saves land
points under `data/benchmarks/points.npy` for the independent runtime-only process.

Product regressions now assert New York City at `(40.7128, -74.0060)` and Tokyo at
`(35.6895, 139.6917)`. At `(35.6762, 139.6503)`, the answer is Asagaya-minami:
GeoNames ID 1865090 is coded `PPL`, so it remains after Eifuku (`PPLX`) is removed.
This source-code limitation is documented rather than patched by city name.

## Runtime

Apple M2, macOS 27.0 arm64, CPython 3.12.8, NumPy 2.3.5, H3 4.5.0; warm OS cache.
The separate runtime process imports neither Shapely nor SciPy. The workload is
10,000 saved area-uniform land points; H3 conversion and result objects are included.

| Measurement | Result |
| --- | ---: |
| Open median over 20 opens | 0.837 ms |
| First query excluding open | 1.262 ms |
| Scalar median / p99 | 13.54 / 241.33 µs |
| One-point vector baseline median / p99 | 74.33 / 91.00 µs |
| Public batch throughput | 436,159 points/s |
| Peak runtime RSS, including harness | 101.91 MB |

The baseline is `next(reverse_many([(lat, lon)]))` on the **same final pack**; it
is a rerunnable comparison with the vector route, not a timing of an archived
pre-review implementation. Each scalar measurement has its own fresh Geocoder and
1,000 warmup calls. Batch throughput is the median of three complete runs. The
scalar path shares addressing, bitmap offsets, value decoding and label unpacking
with the batch path. It avoids singleton arrays and batch-level expansion.

Run `uv run python -m benchmarks.runtime`; [runtime.json](../../benchmarks/runtime.json)
records timings, workload hash, manifest hash, environment and cache conditions.
No cold-cache, cross-platform or independent municipal-accuracy claim is made.

## Verification

Fixture-only suite: **43 passed, 7 skipped**. Rebuilt-world suite: **50 passed**.
Ruff check, Ruff format check and strict mypy pass. Full pack verification passes.
The regenerated fixtures total **2,176,949 bytes**, with their original region
retained. Every one of **554,631** Benelux leaf centres is checked against the
flat oracle, builder certificates, and scalar and batch table lookups. World tests
cover random centres, every resolution-3 pentagon, poles, the antimeridian,
independent source polygons, an independent haversine oracle and city regressions.
The fixture's repeated build is byte-identical and publication is atomic.

All three benchmark reports refer to table manifest SHA256:
`35cc988def0b5b95b683444a4b72c2ed5ad74de4b4695038be1144746c9540a1`.
The reference manifest SHA256 is
`0ae97d40d20bc9884e76122bceb999de51140b01188b86870c6879d0eb92383c`.

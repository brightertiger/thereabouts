# Python read-path performance

> Historical: this document describes the retired Python/Cython client. Its
> commands and API are no longer supported. See [CLIENT_RELEASE.md](CLIENT_RELEASE.md)
> for current builds and [CLIENT_STATUS.md](CLIENT_STATUS.md) for current measurements.

The public reader now meets the requested warm targets on a populated synthetic
pack: **9.375 µs scalar median with Cython**, **11.917 µs in forced Python mode**,
and about **527,000 coordinate lookups/s returning columns** in both modes for
shuffled queries. Open one `thereabouts.client.Geocoder` and reuse it. Choose
`reverse_columns` for analytics; object iterators decode only when advanced.

The previous five-place benchmark reported 195 µs and 5,079 object results/s.
A repeatable before/after comparison uses a larger sample, described below.
The original runtime's 13.54 µs / 436,159 points/s in `EVALUATION.md` used a
different world workload and a smaller result shape. It is a useful performance
target, not an apples-to-apples benchmark.

## What was measured

Apple M2, 8 GiB RAM, macOS 27 arm64, CPython 3.12.8, NumPy 2.3.5, H3 Python/C
4.5.0; the main checkout's integration work was running on this laptop. The
sample contains **4,176 places**, **308,032 stored rows**, and **64 r3 blocks**
spread around 16 global centres. Each block has 64 synthetic cities, sparse r8
rows and coarse r5 controls. Place names contain Unicode; distinct evidence and
relationships exercise catalogue decoding. All seven city method codes occur.
Assignments are invented and cannot establish geographic accuracy.

The installed pack is **3,006,380 bytes**: 1,306,534 catalogue bytes and
1,694,288 spatial bytes, across one catalogue and five spatial shards, plus
manifest/notices. This is a compression/sample measurement, not a world forecast.

There are 44,032 coordinate queries, either clustered or deterministically
shuffled. Each order first populates the lazy cache using the entire query set.
Scalar median/p99 use the next 10,000 queries. Column throughput is the median
of five full-query-set runs; object throughput uses five 10,000-row runs.
Timing includes coordinate validation, H3 conversion, search and public results;
it excludes JSON serialization. Default chunk size is 4,096.

| Access / backend | Scalar median / p99, µs | Columns/s | Objects/s |
| --- | ---: | ---: | ---: |
| Before, clustered, Cython | 195.625 / 230.125 | 154,276 | 4,902 |
| Before, shuffled, Cython | 367.417 / 448.458 | 90,575 | 4,641 |
| After, clustered, Cython | 9.375 / 11.584 | 588,009 | 115,993 |
| After, shuffled, Cython | 9.375 / 11.125 | 526,812 | 114,217 |
| After, clustered, Python | 11.666 / 15.458 | 606,299 | 92,156 |
| After, shuffled, Python | 11.917 / 15.917 | 527,190 | 87,477 |

The column path is NumPy in both modes; these small differences do not establish
a native column-speed advantage. Cython still accelerates reconstruction for
scalar and object results. No additional native kernel was warranted.

Process peak RSS: **127,303,680 bytes before**, **78,200,832 Cython after** and
**77,643,776 Python after**, measured in separate processes. Normal open took
1.94 / 1.29 ms; first lookup 7.56 / 24.95 ms (Cython / Python). First access
validates a spatial shard. These measurements did not evict the OS page cache;
the first-lookup difference is not evidence of a backend speed ratio.

## Profile and changes

`cProfile` runs were separate from latency timing. Before, 5,000 scalar calls
performed **80,000 catalogue record decodes**. Clustered decoding consumed
2.071 of 2.524 profiled seconds. On shuffled calls, repeatedly reopening spatial
shards added 1.291 of 3.853 seconds. Column queries built a `Query`, hit and label
tuple per row, and copied entire block key arrays for each block in each chunk.

* A lazy LRU caches immutable decoded places and their sovereign reference.
  Identity-only reads decode the ID string, not the entire evidence record.
  `cache_bytes` is configurable (zero disables caching); `info()["cache"]`
  reports hits, misses, evictions and retained-byte charges. The **32 MiB**
  default accommodates this measured 8,775,320-byte working set with headroom.
  Charges include strings, nested evidence, result objects and LRU storage,
  conservatively charging objects shared across entries more than once.
* Shards map once on first access and remain mapped until close. OS-managed
  mapped pages are separate from decoded objects. Bounds, selectors, label flags
  and reference ranges are checked at first use, instead of on each lookup.
  Full hash/structural verification remains an explicit installation/open option.
* Numeric batches search independent block ranges together, once per shard,
  then gather labels as arrays. They construct no per-row public result objects.
  Object iterators retain a numeric chunk and materialize only its requested row.
  Returned columns/results remain detached and usable after close.

The serving format, fixtures and exporter did not change. The profile identified
reader work, not a layout obstruction. The independent format decoder remains
available to verification and parity tests.

## Cache misses and limits

The 32 MiB cache holds all 4,176 measured places; this is a **warm working-set**
result. It is not a promise of 20 µs when an arbitrary world query misses the
cache. Two explicit shuffled 5,000-query stress runs measured:

| Budget | Scalar median / p99, µs | Misses / evictions |
| --- | ---: | ---: |
| Disabled | 77.917 / 102.042 | 20,000 / 0 |
| 64 KiB | 97.563 / 145.667 | 11,526 / 11,495 |

The deliberately undersized cache retains only 31 entries. Misses decode and
validate evidence; inserting/evicting also accounts for retained Python objects.
The full profiles are in
[CLIENT_PERFORMANCE_MEASUREMENTS.json](CLIENT_PERFORMANCE_MEASUREMENTS.json).
A real workload exceeding the cache would require a larger measured budget or
further optimization of miss-time evidence decoding/accounting. No format change
is justified by the warm-path results alone. Memory retained by callers, NumPy
chunks and mapped pages is outside the decoded-cache budget.

Real pack size, random world working sets, cold-disk latency and geographic
quality remain unmeasured. The integration marker had not appeared and a main
`build_data.digest_golden` process was active; no main golden input was read.

## Reproduce

Run from the client worktree; the sample generator requires a new output path:

```sh
TMPDIR="$PWD/.cache/tmp" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -m benchmarks.populated_sample --output .cache/populated-sample
TMPDIR="$PWD/.cache/tmp" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -m benchmarks.read_path .cache/populated-sample \
  --backend auto --output .cache/read-native.json
# Repeat with --backend python, then measure intentional cache pressure:
TMPDIR="$PWD/.cache/tmp" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -m benchmarks.cache_pressure .cache/populated-sample \
  --output .cache/cache-pressure.json
```

The before profile/timers were captured at `054d9bc` before changing the reader.
The committed JSON includes the pack identity, inventory, all five repetition
times and complete top-25 cumulative profiles. It is not a performance CI gate
on this shared laptop.

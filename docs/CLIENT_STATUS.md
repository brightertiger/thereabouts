# Thereabouts client implementation status

Phases 1–6 are implemented on `feat/client`, locally only:

* `ed74109` — Add verified golden serving packs and deterministic exporter.
* `bf90c3a` — Add offline Python golden reader and bounded public API.
* `4689230` — Add pinned pack installation and JSON command line client.
* `054d9bc` — Accelerate stored-cell reconstruction with optional Cython.
* `fe5cad9` — Cache decoded places and keep batch lookup columnar.
* `0faac7d` — Add standalone postal and airport serving packs.
* Phase 6 — **Add independent Node reader and shared conformance bundle**
  (this commit; find its hash with `git log`).

Phase 7 remains; the optional MCP server is next.
`thereabouts.client.Geocoder` reads the new packs; the frozen top-level `thereabouts.Geocoder` still reads the original table.

## What is usable

### Independent Node client (phase 6)

[clients/node/README.md](../clients/node/README.md) documents the asynchronous
ESM API, public TypeScript declarations, local pinned import and full verification.
`await Geocoder.open({pack: path})` supports `reverse`, `fromH3`, ordered async
`reverseMany`/`fromH3Many`, postal, all five airport schemes, `info`, `explain` and
`close`. Results are immutable, detached JSON objects with Python-equivalent
IDs, methods, ambiguity, evidence and nulls. The only runtime dependency is
H3-JS 4.5.0. No Python worker, native addon, compiler or build step is involved.

File I/O is asynchronous and page reads close their handles. A 32 MiB accounted
cache budget covers raw buffers and lazily decoded objects. Measured residency
motivated an 8/24 MiB split; the populated sample retains 4,757,630 / 18,086,650
charged bytes without eviction. This bounds retained cache accounting, not total
V8/process memory or caller-retained results. Batch iteration and first-read
validation yield every 256 rows to avoid long uninterrupted loops.

`importPack(source, {manifestSha256, dataDir})` explicitly imports local packs,
verifying hashes/structure before and after copying and atomically publishing the
same immutable store paths and active pointers as Python. Cross-client discovery
is tested locally. Node has no URL downloader, installer resume or pack-list API;
Python's explicit CLI supplies those functions against the same store. Lookup
never uses the network. No Node NumPy-equivalent column API is promised.

[CLIENT_NODE_MEASUREMENTS.json](CLIENT_NODE_MEASUREMENTS.json) records Node
24.21.0 on the same M2/8 GiB/macOS 27 arm64 machine, H3-JS 4.5.0, synthetic
4,176 places / 308,032 rows / 64 blocks, 44,032 shuffled queries and the
3,006,380-byte pack. Warm scalar median/p99: **8.583 / 16.583 µs**. Five object
batches: **105,022–110,640 results/s**, median **108,583/s**. Open **9.125 ms**,
first query **10.870 ms**, first pass **54,589/s**; the OS disk cache was not
flushed. Peak RSS **176,553,984 bytes**. At 5 ms sampling, first-pass event-loop
p99/max **10.002 / 10.568 ms** and warm-batch p99/max **7.279 / 8.937 ms**.
These are synthetic shared-machine measurements, not world or service guarantees.

Reproduce after generating `benchmarks.populated_sample` as described in
[CLIENT_PERFORMANCE.md](CLIENT_PERFORMANCE.md): convert `shuffled.npy` with
`json.dumps(numpy.load(path).tolist())`, then run
`node clients/node/benchmark.mjs PACK QUERIES.json OUTPUT.json`.

The committed shared bundle contains **54** public-result/error vectors generated
from the Python reference and **17** declarative malformed-pack mutations.
Python fallback/native and CLI serialization are checked against it; Node also
exhausts three fixture blocks including a pentagon and polar block. Tests cover
uint16 dictionaries, unsafe integers, duplicate JSON keys, UTF-8, trailing zlib
streams, cache disable/eviction, close during reads/iteration, source callbacks,
concurrent imports, symlinks and incompatible packs. Network is blocked in Node
tests. Both local macOS arm64 Node **22.23.3 and 24.21.0** pass **33 tests**.
The full Python suite passes **568 tests, 7 skipped**; Ruff lint/format (**373
files**), strict mypy (**357 files**), TypeScript declaration checks and Prettier
pass. Node LTS CI is configured but was not run remotely. Other OSes remain
unqualified. The **32,740-byte npm tarball** (102,535 bytes unpacked) passed all
successful shared vectors and local import in a separate offline installation.
Node-imported postal data opens in Python; Python-installed airports open in Node. The package stays private.

Only the format document's stale reverse-only introduction changed; bytes and
exporter are unchanged in this phase. Original runtime/pipeline files remain
byte-identical. The integration marker is absent and main normalization is still
running; no main golden data has been read.

### Postal and airport packs (phase 5)

`python -m build_data.serve export --family postal|airports` exports verified
source observations and their minimal canonical catalogue. The same installer,
listing/verification commands and Python API support independent optional packs.
Use `Geocoder(postal_path).postal("00100", country="AA")` or
`Geocoder(airport_path).airport("ZZZ", scheme="iata")`. Select installed families
with `Geocoder(data_dir=store, packs=["postal", "airports"])`, or explicit paths
with `packs={family: path}`. Missing context is explicit; compatible multi-pack
selection checks epoch, golden/policy digests and H3 version. `info()` now groups
manifests and cache statistics by family. Full usage is in [CODE_PACKS.md](CODE_PACKS.md).

Postal leading zeros, country-specific normalization, source editions, multiple
cities per code and source-coordinate disagreements are preserved. Airports keep
source identity, all five explicit schemes, country-scoped keys, duplicate
observations, closed sites and missing locations. `selected` remains null on
ambiguity; no candidate limit or first-row preference is hidden. Source fields,
per-observation H3/method evidence and original labels remain in immutable
results. Code candidates and places share the configured byte-bounded cache.

The format specification now includes an exact-key container with binary sorted
keys and independently compressed candidate records. Decompression bounds come
from measured per-shard maximum record lengths. The reverse byte layout and
original reverse fixture are unchanged. New synthetic compatible fixtures are
under `tests/fixtures/codes`. New exporter logic lives in `build_data/serve_codes`;
serving-stage dispatch and format validation were extended. Serving export
fingerprints therefore change; original pipeline hashes/files do not.

[CLIENT_CODE_MEASUREMENTS.json](CLIENT_CODE_MEASUREMENTS.json) records the sample:
7 postal observations / **10,917 installed bytes**, 4 airport observations /
**16,739 bytes**, exports **0.066 / 0.074 s**, and warm two-candidate median
**3.042 / 2.625 µs** with cached decoding. Combined peak RSS **85,409,792 bytes**.
This tiny code fixture is correctness evidence, not a world size or accuracy
forecast. No real optional-pack export or independent quality review was run.

The populated reverse sample was remeasured after multi-pack changes:
**10.291 µs Cython / 12.750 µs Python** shuffled warm scalar median;
**531,994 / 530,437 points/s** returning columns. Both requested targets remain
met. Object batches were **107,068 / 82,296 results/s**. The report includes the
full profiles, timings and pack identity. Main integration is still rebuilding
and normalizing; no main golden data has been read.

Phase 5 full native suite: **401 passed, 7 skipped**. Ruff check and formatting
(**367 files**) and strict mypy (**353 source files**) pass. Full fallback suite: **399 passed, 9 skipped** (two native-only cases skipped). Tests additionally cover
standalone optional installation, CLI JSON, compatibility rejection, unlocated
packs with zero catalogue entries, source-join mismatch, provenance multiplicity,
resume/idempotence/relocation, corruption, decompression bounds and cache parity.

### Read-path correction after phase 4

The requested warm targets are met on a **4,176-place, 308,032-row, 64-block**
synthetic sample, with 44,032 coordinate queries across 16 global centres.
Installed pack: **3,006,380 bytes**. The new measured shuffled scalar median is
**9.375 µs with Cython / 11.917 µs forced Python**, versus **367.417 µs** on the
same larger sample before the fix (the accepted five-place baseline was 195 µs).
Shuffled numeric-column throughput is **526,812 / 527,190 points/s**, versus
90,575 before. Object throughput is **114,217 / 87,477 results/s**. Clustered
results, p99s, full profiles, cache-pressure timings and reproduction commands are
in [CLIENT_PERFORMANCE.md](CLIENT_PERFORMANCE.md) and its linked JSON report.

Profiles showed repeated catalogue decoding and shard reopening. Decoded places
now use a lazy byte-bounded LRU, default **32 MiB**, configurable with
`Geocoder(..., cache_bytes=...)`; zero disables it. The sample's retained cache
is 8,775,320 charged bytes. Shards map once on demand. Numeric batches operate on
arrays; object iterators decode only their requested row. The original result
semantics, pack format, binary fixture and exporter are unchanged. Native and
Python peak RSS were **78,200,832 / 77,643,776 bytes** in separate processes.

These are warm working-set timings: disabled/64 KiB cache stress runs measured
77.917 / 97.563 µs medians. Their profiles attribute misses to evidence decoding
and retained-byte accounting. No real-world/cold-disk latency claim is made.

Tests cover lazy/reused detached places, eviction and disabled-cache parity,
deferred object materialization, exhaustive ordinary/pentagon/polar ancestor
parity, mixed shards, unaligned flat labels, both dictionary widths, validation
failure cleanup, input types and close behavior. Current full native checks:
**388 passed, 7 skipped**; Ruff check/format **340 files** and strict mypy
**333 source files** pass. Full fallback suite: **386 passed, 9 skipped**
(the two additional skips require the intentionally absent native module).

The main integration marker remains absent; a `build_data.digest_golden` process
was active on the latest check. No main golden data was read. At `fe5cad9`, original hashed runtime/stage files and phase 1 format/exporter
files remained byte-identical. Phase 5 extends only the new serving modules.

### Optional Cython kernel and wheels (phase 4, historical measurements)

[CLIENT_BUILD.md](CLIENT_BUILD.md) documents backend selection, profiling,
local builds, wheel qualification and remaining performance limits. The native
kernel reconstructs stored H3 cells without introducing geographic decisions.
`backend="python"` forces the reference; default `auto` falls back only when the
extension is missing. Native and fallback results are identical in exhaustive
small-block and public scalar/batch/column tests.

Seven alternating numeric-column runs measured a **39% median throughput gain**
(108,381 → 150,991 points/s) on the same synthetic sample. Public scalar median
was **195 µs** with the extension, p99 **283 µs**, and public-result batches
**5,079 points/s**: the public targets were unmet at that baseline. Catalogue
record decoding accounts for roughly **85%** of the public batch profile;
that finding motivated the completed read-path correction above.
[CLIENT_ACCELERATION_MEASUREMENTS.json](CLIENT_ACCELERATION_MEASUREMENTS.json)
contains exact measurements and limitations. Combined process peak RSS was
114,180,096 bytes; no world measurements were made.

Cython generation is pinned to 3.3.0. Generated C is checked in and regenerated
byte-identically; setuptools builds it without a Cython runtime requirement.
Native and fallback wheels (72,937 / 49,628 bytes) and the 124,458-byte sdist were
built locally. Both wheels passed real fixture lookups in separate clean local
environments. Local pip selected the fallback wheel for simulated unsupported
native tags. `cibuildwheel` configuration includes CPython 3.11–3.14 and an
installed-wheel smoke test that requires the native backend. Only macOS arm64
CPython 3.12 was built/run; other platforms, remote CI and dependency-wheel
availability there remain unverified. Nothing was published.

Final review also fixed reentrant close from a source iterator or numeric-input
callback: closed readers cannot reopen mappings. Three regression cases cover it.
The native full suite passes **381 tests, 7 skipped in 30.71 seconds**. The
fallback full suite passes **379 tests, 9 skipped in 40.91 seconds** (the extra
two skips require the intentionally absent native module). Ruff lint and formatting
(332 files), strict mypy (325 source files including setup.py), both installed-wheel
smoke tests, source-distribution contents and regenerated-C equality passed.
All original runtime/pipeline files and phase 1 format/export modules remain
byte-identical. Environment, caches and build output remain under **1.1 GiB**,
even counting hard-linked environments/cache separately. Only small synthetic
workloads ran; no main-checkout golden payload or ledger was opened.

### Installation and CLI (phase 3)

[DATA_INSTALLATION.md](DATA_INSTALLATION.md) documents local or pinned-URL
installation, persistent store discovery, listing/full verification, and JSON
`reverse`, `h3`, typed `resolve`, `batch`, `info` and `explain` commands. Run
`python -m thereabouts --help` or the installed `thereabouts` entry point.
`Geocoder(data_dir=...)` opens the active reverse pack; an explicit pack path
bypasses discovery. Lookups never access the network.

Installs require an operator-trusted manifest SHA256; URL manifests additionally
require their trusted byte count. Verified files resume at shard boundaries.
The completed pack is fully verified before immutable publication and atomic
activation. Old versions remain available to existing readers. No data host is
configured or contacted; external network access remains guarded in tests.

A local install of the 208,592-byte synthetic pack took **0.427 seconds** including
full verification; peak process RSS was **41,992,192 bytes**. See
[CLIENT_INSTALL_MEASUREMENTS.json](CLIENT_INSTALL_MEASUREMENTS.json). CLI entry
point rebuilding used this worktree's environment and cache, with
`uv sync --frozen --offline`. The installed command's help and full fixture verification
passed. No code or dataset was uploaded.

Phase 3 final checks: **374 passed, 7 skipped in 33.83 seconds**; whole-worktree
Ruff lint, formatting (325 files) and strict mypy (318 source files) passed.

### Python client (phase 2)

[PYTHON_CLIENT.md](PYTHON_CLIENT.md) documents `Geocoder(pack, verify=False)`,
`reverse`, `from_h3`, bounded `reverse_many`/`from_h3_many`, numeric
`reverse_columns(decode=False)`, `info` and `explain`. Coordinates become r8 once;
logical ancestors preserve stored methods, canonical IDs, nulls and coverage.
Frozen results preserve evidence, separate sovereigns, distance bands and warnings.
NumPy batches group block reads and restore order. Numeric columns have validity
masks and pack-local references; optional decoding supplies public IDs/names.

```python
from thereabouts.client import Geocoder

with Geocoder("tests/fixtures/serving", verify=True) as geo:
    print(geo.reverse(12.97, 77.59).to_dict())
```

The initial single-mapping reader has been replaced by lazy retained mappings
and a bounded decoded-place cache (see the correction above). Close synchronizes
with active chunks and invalidates buffered iterators. Normal opening validates
inventory/headers and assumes an immutable verified installation; `verify=True`
performs full checksums and structure verification. Lookup never installs data.

Phase 2 adds 29 tests for methods, immutable evidence, distance/null/coverage,
coordinate/H3 validation, logical versus geometric parent boundaries, exhaustive
NumPy/scalar ancestor parity, bounded batches, numeric columns, concurrent reads,
close, corruption and incompatible manifests. The network guard stays enabled.

The integration report has **not** said `integrate finished` during this work;
main-checkout golden data has not been read. The verified world counts supplied
by the owner are not independently confirmed here. Continue with synthetic inputs
until the marker exists **and** no `build_data` process is running there.

### Serving exporter (phase 1)

`python -m build_data.serve export` turns a completed, verified `golden-2` manifest
into an immutable reverse pack. It verifies all manifest-listed hashes, relevant
schemas, source quality records and pending-join status, builds the minimal
catalogue closure, and compares every emitted place field and stored cell with
the source transformation before atomic publication. No ledger, network, source
workspace writes or geographic reassignment are involved.

`python -m build_data.serve verify <pack>` performs full hashes and structural
verification. The format is specified independently of Python in
[SERVING_FORMAT.md](SERVING_FORMAT.md), including byte offsets, H3 addressing,
nulls, coverage, IDs, method bits and catalogue records. The small binary example
is [tests/fixtures/serving](../tests/fixtures/serving/README.md). It carries Unicode,
all v2 city methods, distant-nearest semantics, empty ocean and unassigned land.

The exporter is resumable by verified shard checkpoints, keyed by golden bytes,
release metadata, code hashes, tool versions and shard target. Repeating a completed
export performs verification without rewriting files. Existing output with changed
inputs or corruption is refused. A restart reconstructs the disk-backed catalogue
index; verified spatial shards are reused. Old staging from a different fingerprint
is retained for explicit cleanup. The exporter uses a POSIX advisory lock; Windows
export is not qualified.

Use this worktree's environment and temporary directory:

```sh
mkdir -p .cache/tmp
TMPDIR="$PWD/.cache/tmp" UV_CACHE_DIR="$PWD/.cache/uv" uv sync --frozen
TMPDIR="$PWD/.cache/tmp" .venv/bin/python -m build_data.serve verify tests/fixtures/serving
```

For an independently reproducible small export, generate synthetic inputs here:

```python
from pathlib import Path
from tests.serve.fixtures import golden
from build_data.serve.export import export

manifest, release = golden(Path(".cache/client-example/input"))
export(manifest, release, Path(".cache/client-example/pack"))
```

For real data, use an explicit completed golden manifest and a release JSON with
version, identity epoch, pinned source releases, attribution and checksummed licence
notices. The required JSON and CLI are documented in the format specification.
Do not point an export at the running pipeline's workspace or incomplete manifest.

## Measurements and validation

[CLIENT_MEASUREMENTS.json](CLIENT_MEASUREMENTS.json) records the measured pack and
input hashes. The workload is **synthetic**: seven blocks, 67,230 stored cells
(four dense r8 blocks plus sparse/empty controls), six input places and five
retained places. It deliberately repeats labels and has a tiny catalogue. Its
compression ratio, catalogue size and timings are not forecasts for golden world
data or evidence about geographic answer quality.

Machine: Apple M2, 8 GiB RAM, macOS 27.0 arm64; Python 3.12.8, H3 Python/C 4.5.0,
PyArrow 23.0.1. Measurements ran alongside the owner's world verification process.
The report gives exact bytes, export elapsed time, process peak RSS, sampled peak
scratch usage, and 10,000 warm internal label searches. The label timing excludes
coordinate conversion, catalogue decoding and public result construction. It is
not a public API benchmark. The ZIP uses deflate level 6 for size measurement;
this ZIP is a measurement artifact, not an installer input. The installer
consumes unpacked directories or individually pinned URL artifacts.

| Measurement | Result |
| --- | ---: |
| Installed pack (including manifest and notices) | 208,592 bytes |
| Spatial / catalogue payloads | 202,680 / 1,042 bytes |
| Measured ZIP | 125,752 bytes |
| Export, including verification | 1.358 seconds |
| Peak process RSS (including input generation) | 116,178,944 bytes |
| Sampled peak staging disk | 229,611 bytes |
| Warm internal label search, median / p99 | 4.417 / 6.250 µs |

Reproduce on a **new** worktree-local path:

```sh
TMPDIR="$PWD/.cache/tmp" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -m benchmarks.serving_export --output .cache/new-serving-measurement
```

The conformance tests exhaust actual r8 descendants in four small fixture blocks,
including a pentagon, and independently compare stored ancestors, IDs, methods,
nulls and absence. Tests cover flat/uint8/uint16 labels, catalogue closure,
determinism, relocation, interrupted resumption, invalid generations and joins,
overlapping ancestors, bad references, UTF-8, headers, checksums, paths, symlinks,
coverage and version/epoch mismatches. The existing network guard remains enabled.

Full validation commands, from this worktree:

```sh
TMPDIR="$PWD/.cache/tmp" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/pytest --basetemp=.cache/test-final -q
.venv/bin/ruff check
.venv/bin/ruff format --check
.venv/bin/mypy
```

Phase 1 review checks: **319 passed, 7 skipped in 27.90 seconds**. The skipped tests
require explicitly selected world data; none were marked passed. Whole-worktree
Ruff check and formatting (294 files), strict mypy (287 source files), and the
build CLI's export/verify smoke test passed. No external CI was run. Original
runtime/pipeline files were compared against the starting commit `d3b4d94` and
are unchanged. At phase 1, added environment, cache, tests and measurement artifacts
occupied less than 0.9 GiB even when counting the hard-linked environment/cache separately.

Phase 2 public API measurements are in
[CLIENT_READER_MEASUREMENTS.json](CLIENT_READER_MEASUREMENTS.json). The same
208,592-byte, seven-block synthetic pack was queried at 10,000 centres clustered
in four dense blocks. Warm scalar median/p99: **201.375 / 259.792 µs**;
public-result batch: **4,724 points/s**; numeric columns: **102,433 points/s**.
Peak process RSS was **111,919,104 bytes**, full verification **0.485 seconds**.
Those public-result performance targets were not met; phase 4 profiling and
measurements above separate catalogue decoding from the numeric kernel. No cold-disk or world access
measurement was made. The machine/dependencies are the same as above.

Phase 2 final checks: **348 passed, 7 skipped in 44.35 seconds**; whole-worktree
Ruff lint, formatting (309 files) and strict mypy (302 source files) passed.
Every original runtime/build-stage file still matches `d3b4d94`; phase 1 format/export modules are also unchanged.

## Deliberately deferred and how to continue

* Phase 3 follow-ups: signed release index/key rotation, byte-range resume,
  explicit pruning and Windows/power-loss qualification. Local/URL installation
  and file-level resume are complete; no remote release exists to qualify.
* Phase 7: optional stdio MCP integration over the existing Python API. No MCP
  implementation is included at the phase 6 boundary.
* Remaining performance work: representative real-pack access and cache-miss
  measurements. Warm synthetic targets are met; cold/world behavior is unverified.
  Cross-platform wheels require native-runner CI
  qualification before release; no remote CI or publication was attempted.
* Ranked bitmaps and catalogue/layout optimization await representative real-data
  measurements. Format 1.0 intentionally specifies only sparse uint16 keys and
  the measured flat/dictionary label choice. Extending it requires an explicit
  supported format revision and conformance cases.
* A completed real v2 export remains unverified. No real-world cells, catalogue,
  accuracy set, holdout, pack size, export disk bound or final quality gate was
  evaluated here. One read-only real export into this worktree is authorized
  only after `integrate finished` and no active `build_data` process, with
  memory under 1.5 GB and output under 3 GB. Those gates have not opened. Arrow row batches and SQLite's
  page cache are not process-wide memory limits. Temporary disk for the full
  catalogue index has not been measured at world scale.
* Admitted-source licence completeness and redistribution rights still require
  the owner's release review. The exporter preserves supplied notices and the
  golden draft notice; it does not automate source admission or legal clearance.
  No code licence or real data-release metadata was chosen for the owner.

## Frozen-file follow-ups

All files that existed under `src/thereabouts/` and `build_data/` at task start
remain byte-identical. New code lives in `src/thereabouts/packs/`,
`src/thereabouts/reading/`, new
client/result/column/store/CLI modules, `src/thereabouts/installing/`,
`src/thereabouts/commandline/` and `build_data/serve/`; these are not hashed by
the existing normalization stage. No pipeline entry point was modified or invoked.

After the running build is safe to change, replace the original runtime and
top-level exports through a separately reviewed change. Before doing so, move
build-time dependencies on `format`, `hierarchy`, `errors`, `models`, `index`,
`table` and `manifest` out of the retired runtime, or update their callers.
Changing `src/thereabouts/format.py` or `build_data/hierarchy.py` invalidates base
cell fingerprints. Changes under existing `golden`, `cities` or `normalize_cells`
also invalidate normalized implementation hashes and can invalidate review gates
and checkpoints. Adding the serving exporter to the controller should wait for
that coordinated change. Do not remove those imports while the current pipeline
is running.

Open owner decisions before release: code licence; real source/notice bill of
materials; data version and catalogue epoch; acceptance of measured real-pack
size and quality. The already-decided golden-first, explicit-install, Node-only,
postal-plus-airport scope is unchanged.

All project/data writes stayed in this worktree, with a separate `.venv` and
local temporary/cache paths. The other checkouts and pipeline data/ledger were
not modified. Work is committed locally only; nothing was pushed, uploaded,
published or submitted as a PR. Local Git commits use the worktree's normal
shared Git metadata.

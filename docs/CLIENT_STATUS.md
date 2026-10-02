# Thereabouts client implementation status

Phase 1 (serving format and exporter) is implemented on `feat/client`. This is a
local implementation handoff, not a release. The latest phase commit is identified
in `git log` by **Add verified golden serving packs and deterministic exporter**.
Phases 2–7 have not been started. In particular, the top-level `thereabouts.Geocoder`
still reads the original table; it does **not** read the new packs.

## What is usable

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
there is no installer/archive contract yet.

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

Final review checks: **319 passed, 7 skipped in 27.90 seconds**. The skipped tests
require explicitly selected world data; none were marked passed. Whole-worktree
Ruff check and formatting (294 files), strict mypy (287 source files), and the
build CLI's export/verify smoke test passed. No external CI was run. Original
runtime/pipeline files were compared against the starting commit `d3b4d94` and
are unchanged. Added environment, cache, tests and measurement artifacts occupy
less than 0.9 GiB even when counting the hard-linked environment/cache separately.

## Deliberately deferred and how to continue

* Phase 2: public Python `Resolution`/candidate API, coordinate/H3 validation,
  bounded ordered batches, lifecycle/thread semantics and NumPy lookup. The new
  `thereabouts.packs` modules are internal format/verification primitives, not
  an alternative public API. No top-level compatibility alias was added.
* Phase 3: explicit data installation, store selection, URL/local import,
  trusted manifest pins, atomic activation and query CLI. Only build-time export
  and verify commands exist now; no lookup can trigger data installation.
* Phases 4–7: profiling-led Cython/wheels, postal and airport packs, independent
  Node reader with shared public-result vectors, optional MCP integration.
* Ranked bitmaps and catalogue/layout optimization await representative real-data
  measurements. Format 1.0 intentionally specifies only sparse uint16 keys and
  the measured flat/dictionary label choice. Extending it requires an explicit
  supported format revision and conformance cases.
* A completed real v2 export remains unverified. No real-world cells, catalogue,
  accuracy set, holdout, pack size, export disk bound or final quality gate was
  evaluated here. Validate on a small verified real snapshot first; a full world
  export is a separate resource-budgeted task. Arrow row batches and SQLite's
  page cache are not process-wide memory limits. Temporary disk for the full
  catalogue index has not been measured at world scale.
* Admitted-source licence completeness and redistribution rights still require
  the owner's release review. The exporter preserves supplied notices and the
  golden draft notice; it does not automate source admission or legal clearance.
  No code licence or real data-release metadata was chosen for the owner.

## Frozen-file follow-ups

All files that existed under `src/thereabouts/` and `build_data/` at task start
remain byte-identical. New code lives in `src/thereabouts/packs/` and
`build_data/serve/`; neither directory is hashed by the existing normalization
stage. No pipeline entry point was modified or invoked.

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

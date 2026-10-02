# Reading golden serving packs in Python

`thereabouts.client.Geocoder` reads an immutable `thereabouts-pack-1` reverse
pack without network access. Install the project and its NumPy/H3 dependencies
in this worktree's environment, then select a pack directory explicitly:

```python
from thereabouts.client import Geocoder

with Geocoder("tests/fixtures/serving", verify=True) as geo:
    answer = geo.reverse(12.97, 77.59)
    same_cell = geo.from_h3(answer.reference.h3)
    print(answer.to_dict())
    for result in geo.reverse_many([(12.97, 77.59), (0, 180)]):
        print(result.status)
```

`Geocoder(data_dir="/path/to/store")` opens an explicitly installed active pack;
`Geocoder()` uses the environment/platform store. See
[DATA_INSTALLATION.md](DATA_INSTALLATION.md) for installation and JSON CLI usage.

The committed fixture is synthetic and is not geographic evidence. For another
verified golden snapshot, use the exporter described in
[SERVING_FORMAT.md](SERVING_FORMAT.md). The old `thereabouts.Geocoder` is still
the original reader: its files and top-level exports are frozen pending pipeline
integration. Use the explicit `thereabouts.client` import for these packs.

## Results and evidence

Every lookup returns a frozen `Resolution`. `selected` is one candidate for
`matched`, otherwise null; `candidates` is an ordered tuple. A coordinate/H3
lookup has at most one candidate. `require_one()` returns it, returns None for no
match, and raises `AmbiguousResultError` for an ambiguous envelope. Future exact
code packs will supply multiple candidates; no first-row selection is implied.

The candidate's `city`, `state`, `country` and `sovereign` are nullable `Place`
records with public IDs, names, settlement kind, relationships and local evidence.
A city slot can hold a village. The `place` slot is null for spatial context;
it is reserved for a source entity. Country and sovereign are separate data
relationships. An unspecified code system stays null; the client does not infer
one from a code's spelling. Source IDs and name provenance are immutable JSON
values; the pack's pinned source releases and attribution are in `result.data`.

`methods` preserves the stored city, country, state and land assignment methods.
Confidence has a descriptive basis and no calibrated probability. Nearest
answers expose a distance band and the pack's cutoff, with `exact_m=None`.
`rural_nearest_distant` adds `distant_nearest`; inferred urban/town extents add
`inferred_extent`. These describe evidence at the reference cell centre.

`reference` records the input r8 H3 cell and the stored ancestor, if any. The
reader converts coordinates exactly once at r8 and walks logical parents. It
never recomputes a coarser cell from the original coordinate. H3 strings are
normalized to lowercase; only valid r8 cells are accepted. Coordinates must be
finite real numbers within latitude ±90 and longitude ±180. Booleans and strings
are rejected; +180 is normalized to -180.

The absence statuses have distinct meanings:

| Status | Meaning |
| --- | --- |
| `unassigned` | A stored land row exists with all place references null. |
| `ineligible` | The covered block has no row at any logical ancestor. |
| `outside_coverage` | The block is not included in this partial pack. |
| `invalid_input` | A batch collected an invalid row. |

A country/state answer without a city remains `matched`. A world manifest with
an absent block is corruption, not outside coverage. `not_found` and `ambiguous`
are reserved for resolvers with other candidate semantics.

`to_dict()` returns detached JSON-compatible data, including provenance. `info()`
returns a detached manifest with source releases, notices and its SHA256.
`explain(answer)` adds the explicit indication that full raw golden evidence is
not installed. All three are local operations. Strings, results and explanations
remain usable after the reader closes.

## Batches and analytics

`reverse_many` and `from_h3_many` return bounded iterators in input order, grouping
lookups by block within each chunk. The default is 4,096 rows. `chunk_size` accepts
any positive integer so the caller controls the memory/latency tradeoff; there is
no guessed global input limit. The default `errors="raise"` rejects invalid
inputs. `errors="collect"` emits `invalid_input` for individual malformed rows,
with a reason and no echo of their raw values. Data errors always fail the
operation. Iteration is not transactional: earlier chunks may have been yielded
when a later input or data error occurs. Iterators consume at most one chunk ahead.

`reverse_columns` yields detached NumPy `Columns` chunks, avoiding place/result
construction. `h3`/`stored_h3` use uint64, references/flags use uint32, and boolean
`valid`/`present` masks distinguish invalid inputs and absent stored rows. Zero
place references are null. These integers are **local to the exact manifest**;
never join them across packs or serialize H3 uint64 as a JavaScript number.
`decode=True` adds a mapping from the chunk's distinct references to `Place`
records; this supplies public IDs and names without repeating their decoding for
every row. Flags use the documented [serving format](SERVING_FORMAT.md).

Open once per process and use a context manager or `close()`. Close is idempotent;
all later operations, including buffered iterators, fail with
`ClosedGeocoderError`. Concurrent reads share a lock; close waits for an active
chunk. This is thread safety, not a parallel throughput promise. Each process
must open its own handle. The reader retains at most one spatial and one catalogue
mapping, replacing each on shard changes; there is no full-world object cache.

## Integrity and performance

The default `backend="auto"` uses the optional Cython reconstruction kernel when
installed; `backend="python"` forces the reference path. See
[CLIENT_BUILD.md](CLIENT_BUILD.md) for profiling, parity and local wheel checks.

Normal opening checks compatibility and all listed payload sizes. First access
to a shard validates its container directory/bounds, and records are checked as
decoded. This assumes a previously verified, immutable installation; it is not a
full integrity audit and does not detect every same-size mutation. `verify=True`
checks every payload SHA256 and all structural invariants before use. Never
modify a pack in place while a reader is open.

Failures derive from `thereabouts.errors.GeocoderError`. Input and ambiguity
errors live in `thereabouts.client_errors`; data installation/lifecycle errors
remain in `thereabouts.errors`; serving corruption and unsupported formats are
in `thereabouts.packs.errors`. Their modules stay separate while original runtime
files are frozen.

[CLIENT_READER_MEASUREMENTS.json](CLIENT_READER_MEASUREMENTS.json) records an
Apple M2 / 8 GiB / macOS 27 / Python 3.12 sample with 67,230 synthetic rows and five
retained places. Reproduce against the pack produced by `benchmarks.serving_export`:

```sh
TMPDIR="$PWD/.cache/tmp" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -m benchmarks.client .cache/serving-measurement-reviewed/pack \
  --output .cache/reader-measurement.json
```

Public results are considerably more expensive than numeric columns. These
measurements include H3 conversion; they do not establish world latency or the
product plan's performance targets. No disk cache eviction or real-world catalogue
pressure was tested. Optimize only after profiling these separate costs.

# Source acquisition contract (version 1)

This is the shared groundwork for [DATA_PLAN.md](DATA_PLAN.md). Implement only
your source adapter and its tests; shared helpers, schemas, dependency files and
other adapters belong to the coordinating agent. No real source data was acquired
while building this layer. The four adapters deliberately raise
`NotImplementedError` (CLI exit 2) until implemented; a stub is never recorded as
completed work. Reconciliation and H3 rebuilding remain separate stages.

## Entry points and paths

Each adapter implements `download(workspace: Workspace) -> None` and
`normalize(workspace: Workspace) -> None`. Explicit CLI keys and module names are
`osm_land`, `overture`, `geonames`, `geoboundaries`. The CLI runs sources/stages
sequentially; individual units inside adapters own their checkpoints.

```sh
uv sync
uv run python -m build_data.acquire osm_land --stage download
uv run python -m build_data.acquire overture --stage normalize
uv run python -m build_data.acquire geonames --stage all
uv run python -m build_data.acquire geoboundaries
uv run python -m build_data.acquire all
```

With `.venv` activated the exact entry point is
`python -m build_data.acquire <source> [--stage download|normalize|all]` or
`python -m build_data.acquire all`. `--stage` defaults to `all`;
`--data-dir /absolute/path` overrides the default `data/` root. `uv run` installs
the `acquire` dependency group through the default `dev` group. It contains
PyArrow, DuckDB, Shapely and pyshp; HTTP uses the standard library.

`Workspace(root: Path = Path("data"))` provides `prepare()`, `raw(source)` →
`data/raw/<source>/`, `normalized(source)` → `data/normalized/<source>/`, `work` →
`data/work/`, and `ledger_path` → `data/work/ledger.sqlite3`. Put temporary source
work in `work/<source>/`. Call `check_budget(required_bytes: int = 0)` **before
every unfinished unit**, with estimated incremental bytes where known. It checks
20 GB free disk and the 45 GB workspace cap (decimal bytes). It is an admission
check, not a reservation across processes or a live RSS monitor. The CLI checks
before each stage too. Keep total runtime concurrency within the plan: one
geometry worker, two download streams, DuckDB `memory_limit='2GB'`, `threads=2`,
and at most 6 GB spill in `work/`. Do not run four world normalizers simultaneously.

## Downloads and checkpoints

Public helpers are exported from `build_data.acquire`:

```python
download_file(url: str, destination: Path, *, expected_size: int,
              etag: str | None = None, last_modified: str | None = None,
              sha256: str | None = None, retries: int = 5,
              timeout: float = 60, backoff: float = 1) -> Path
fingerprint(inputs: Mapping[str, object]) -> str
sha256_file(path: Path) -> str
atomic_output(path: Path, validate: Callable[[Path], None])  # context manager
Ledger(path: Path)
ledger.is_complete(stage: str, unit_id: str, inputs_hash: str) -> bool
ledger.completed_outputs(stage, unit_id, inputs_hash) -> tuple[Path, ...] | None
ledger.complete(stage, unit_id, inputs_hash, outputs: Sequence[Path],
                *, metadata: Mapping[str, object] | None = None) -> None
```

Freeze an inventory first: URL, resolved route, release, size, ETag/Last-Modified,
publisher SHA256 if available, retrieval date and licence notices. Use a separate
raw snapshot directory per release; never silently refresh mutable pins. The
downloader needs the expected size and pins a strong ETag (preferred) or
Last-Modified from the first accepted response if not supplied. Weak ETags alone
are insufficient. Keep both `<destination>.part` and
`<destination>.download.json`; the receipt persists pins and the completed SHA256.
Interrupted bodies are fsynced and resumed with Range/If-Range. Wrong range/length,
changed or missing validators, encoded bodies and a 200 for a nonzero range fail
before appending. Network failures, 408/429 and 5xx retry with capped exponential
jitter; `retries` counts retries after the first attempt. A full orphan `.part`
can be verified and published without network. Existing files are rehashed and
skipped offline. Corrupt existing files or checksum failures raise explicitly;
retain evidence and redo only the affected unit. A changed remote snapshot needs
a newly pinned inventory/path, never automatic pin replacement.

Whole-file SHA256 without a publisher checksum establishes local cache identity,
not publisher authentication. Adapters must also check ZIP member CRCs, Parquet
footers/schema/counts, or other source integrity before recording completion.
Use stage names `<source>.download` and `<source>.normalize`; keep unit IDs stable
(object/member/row group/byte interval). Fingerprints must include actual input
SHA256s, release/validators, all filtering parameters, builder/policy version and
`SCHEMA_HASHES[kind]`. JSON must be serializable and contain no NaN. The sequence is:

1. Skip only if `ledger.is_complete(...)` verifies the matching inputs and **all**
   output sizes/hashes. This is verification I/O, with no repeat download/transform.
2. Check disk budget, then build. Use `atomic_output(path, validator)` for ordinary
   files or `write_partition` below for Parquet. Close the writer before leaving
   the context; validation and fsync precede atomic rename and directory fsync.
3. After **all** outputs are published, call `complete(...)`. Metadata records
   counts, extents, rejected rows and verification results. Empty units may record
   `outputs=[]` plus a zero-row count. A network error is never an empty unit.

SQLite uses WAL, FULL synchronous transactions and a 30-second busy timeout.
Separate sources/processes can complete different units concurrently. Only one
writer may own a particular unit or download destination. Multi-file publication
is committed by the ledger marker; consumers must not glob partly published
directories. A crash leaves no false completion; rebuild or revalidate/adopt an
orphan. Input changes produce new fingerprint directories and replace the unit's
completion record only after success. Never edit published outputs in place.

After successful normalization, atomically write
`normalized/<source>/manifest.json` (using `io.write_json`) containing
`schema_version: "1"`, `source`, `source_release`, and `units`, a list of
`{"stage": "<source>.normalize", "unit_id": "...", "inputs_hash": "..."}`.
Include all current units and use `completed_outputs` to verify each. List
code maps, rejection audits and other non-Parquet outputs under `auxiliary` as
paths with size/SHA256. Reconciliation reads only these manifests and their
verified ledger outputs, never a recursive glob including obsolete snapshots.
Publish a new manifest only when every current unit succeeds; validate each
required manifest's release against the frozen inventory before reconciliation.

## Fixed Parquet schemas

Use `pa.Table.from_pylist(rows, schema=SCHEMAS[kind])`, including typed nulls;
no ad hoc columns. `AREAS`, `PLACES`, `NAMES`, `SCHEMAS` and `SCHEMA_HASHES` are
exported. String IDs are opaque and source-scoped; preserve them across geometry
splits (distinguish parts in provenance). All schemas end with required strings
`source_release, license, provenance`. `provenance` is a JSON object string with
required nonempty `source_url`, `license_url`, `attribution`, and source-specific
fields. Preserve upstream `sources`, schema fingerprint, hierarchy, perspectives,
names/field-language evidence, transformations, original IDs, retrieval dates and
represented/update/build dates there as applicable. This keeps nested source
detail without inventing extra relational schemas.

| Dataset | Columns, in order (before the three provenance columns above) |
| --- | --- |
| areas | source, source_id, entity_id, kind, subtype, admin_level, parent_source_id, country_code, subdivision_code, name, name_en, geometry, xmin, ymin, xmax, ymax, is_land, is_territorial |
| places | source, source_id, kind, name, name_en, latitude, longitude, feature_class, feature_code, subtype, country_code, admin1_code, admin2_code, parent_source_id, population |
| names | source, source_id, entity_source_id, name, language, name_kind, is_preferred, is_short, is_colloquial, is_historic, valid_from, valid_to |

All columns are strings except `geometry` (binary WKB), coordinates/bboxes
(float64), population (nullable int64), extent flags (nullable bool), and name
flags (required bool, false when not asserted). Required across all datasets:
source, source_id and the three provenance columns. Additional required fields:
areas entity_id/kind/geometry/bbox; places kind/name/latitude/longitude; names
entity_source_id/name/all four flags. All other fields are nullable; use null,
never empty strings, for unknown values. Source keys match CLI keys exactly.

Areas use valid, nonempty 2D Polygon/MultiPolygon WKB in EPSG:4326, longitude/x
first. Store the actual finite geometry bounds; no wrapped xmin>xmax bboxes.
Preserve seam/polar geometry; audit any repair or split, and never silently discard
an invalid input. `source_id` is the area record ID, `entity_id` the associated
division ID (or the same ID when no separate entity exists). Names and parent IDs
refer to **entity IDs**, so Overture names join areas through `entity_id`, not the
area ID. Keep both territorial/land variants and their flags for reconciliation.
For split parts, duplicate source/entity IDs are expected; never deduplicate
solely by source_id. Use kinds such as land/country/territory/state/county/locality;
preserve source subtype and admin_level as given rather than equating source levels.
Use `places.kind="settlement"` for GeoNames; retain other Overture division roles
and parents as points instead of discarding the entity graph.

Country codes are uppercase ISO alpha-2 plus the plan's XK policy; preserve raw
codes in provenance when conversion is needed. Subdivision codes are actual ISO
codes only. GeoNames admin1/admin2 codes stay source codes; do not call them ISO.
Population zero differs from unknown/null. Normalize display text to NFC and
whitespace per the plan; English must be explicit, never inferred from ASCII.
Retain alias language (including source special tags), name_kind, flags and raw
validity strings; display-name filtering belongs to reconciliation. Use a stable
derived alias ID when the source has none. Cross-partition uniqueness, hierarchy,
foreign keys, settlement eligibility, territory and naming policy are adapter/
reconciliation checks, beyond structural schema validation.

## Bounded partitions and validation

`workspace.partition(source, kind, unit_id, inputs_hash, part=0)` returns
`normalized/<source>/<kind>/<inputs_hash>/<sha256(unit_id)>-00000.parquet`.
One file is one read partition; a directory or an entire country is **not** a
bounded partition. Increase `part` deterministically within a unit. Keep rows in
stable source order; do not spatially duplicate whole admin polygons here.

`validate_table(table: pa.Table | pa.RecordBatch, kind) -> None` checks exact
ordered types/nullability, required values, provenance, coordinates, population,
WKB validity and matching bboxes. `write_partition(path, kind, batches) -> None`
streams tables/batches to zstd Parquet with plain values and validates before
publication. `validate_parquet(path, kind) -> None` validates an existing part.
Dictionary/delta encodings are rejected before decoding to avoid hidden expansion.
Limits: **8 MB per row, 32 MB per input batch/row group, 128 MB per file on disk,
in uncompressed row-group bytes, and in decoded Arrow bytes**. Aim for 16 MB
batches and 64 MB files to leave encoding overhead; rotate before limits. A
writer that exceeds a bound fails without replacing old output. Split/isolate
oversized geometries; never increase the limit or build a global GeoDataFrame.
Read one file or stream row groups at a time; expand geometry in small batches.
These conservative bounds leave room under roughly 2 GB per reader, but do not
assert a measured process-tree RSS bound. Never `read_table` the whole dataset.

Simplifications: sequential `.part` append and whole-object verification replace
the 8 MiB range/chunk ledger; fingerprint directories replace a content-addressed
object store; source-unit file partitions precede spatial tiling in reconciliation;
nested source details stay in JSON provenance. Resource checks are local unit
admission guards, not a scheduler or continuous memory/spill monitor. Real-source
integrity, semantic policies, world resource measurements and H3 work are still
the source/reconciliation agents' responsibility.

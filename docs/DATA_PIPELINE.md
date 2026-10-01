# Source acquisition pipeline

The four implemented adapters acquire pinned raw inputs and publish validated,
bounded Parquet for [DATA_PLAN.md](DATA_PLAN.md). Reconciliation and H3 building
are separate stages. Acquisition retains source identities, naming evidence,
administrative roles and provenance; it does not decide which source wins.

## Commands

```sh
uv sync
uv run python -m build_data.acquire all
uv run python -m build_data.acquire status
uv run python -m build_data.acquire osm_land --stage download
uv run python -m build_data.acquire overture --stage normalize
uv run python -m build_data.acquire geonames --stage all
uv run python -m build_data.acquire geoboundaries
```

With `.venv` activated, `python -m build_data.acquire all` is equivalent. Source
keys are `osm_land`, `overture`, `geonames`, `geoboundaries`; `--stage` defaults to
`all`. Every command accepts `--data-dir /absolute/path`, defaulting to `data/`.
The explicit source mapping in `__main__.py` runs stages sequentially.

`status` reads inventories, manifest counts, file sizes and SQLite completion
records. It reports downloaded units/bytes, normalized units/partitions/bytes,
and rows by kind, including completed checkpoints when no final manifest exists.
It never downloads, extracts, transforms, initializes a missing workspace or
rehashes world datasets. “Complete” is the recorded completion state with present
outputs of the recorded sizes; run `all` to verify full SHA256 integrity. Ordinary
SQLite read connections may use WAL/SHM sidecars while another process runs.

## Current verified snapshot

| Source | Pinned release | Contribution | Rows | Licence |
| --- | --- | --- | ---: | --- |
| OSM land | `2026-10-01T03:37:19Z` (data date `2026-10-01T00:00:00Z`) | Split physical-land polygons, overlaps retained | 873,311 areas | ODbL 1.0; OpenStreetMap contributors |
| Overture divisions | `2026-09-23.1` | All division roles, area variants, parents and language-tagged aliases | 1,080,670 areas; 4,688,229 places; 9,893,479 names | ODbL 1.0; Overture/OpenStreetMap and recorded upstream attribution |
| GeoNames | `20261001T160939Z` | All P and A classes and aliases referring to retained entities | 5,775,916 places; 10,884,490 names | CC BY 4.0; GeoNames |
| geoBoundaries | `gbOpen-a5b064cdf7dc8c3cb70b` | Every available gbOpen ADM0/ADM1, plus PHL ADM2 | 3,839 areas | Per-layer source licence, preserved verbatim |

OSM contributes 1,220 partitions; Overture 1,350; GeoNames 258; geoBoundaries
440 from 430 layer units. Overture's 1,080,667 source areas produce three extra
rows after lossless geometry splitting. GeoNames audits six rejected alias lines;
excluded non-P/A features and aliases of excluded entities are counted separately.
The other three current snapshots report zero rejected features.

geoBoundaries has 18 distinct publisher licence labels, including ODbL, CC BY,
CC BY-SA, CC0/public domain and country-specific terms. See
`raw/geoboundaries/licenses-resolved.json`, each row's `license`, and its
`provenance.license_url`; gbOpen is not a single licence. Corrected inventory
records and source-count discrepancies retain both the original evidence and
corroborating unsimplified SHP/GeoJSON identities. Coverage gaps are reported.

## Files and module responsibilities

```text
data/
  raw/<source>/inventory.json        # frozen source pins and retrieval evidence
  raw/<source>/<snapshot>/...        # original archives/Parquet, receipts, notices
  normalized/<source>/manifest.json  # sole current output list, committed in ledger
  normalized/<source>/<kind>/<inputs_hash>/<sha256(unit)>-00000.parquet
  normalized/<source>/audits/...     # per-unit verification (OSM audits sit by parts)
  normalized/<source>/verification-<hash>.json  # immutable final verification
  normalized/<source>/verification.json         # latest report for inspection
  work/ledger.sqlite3               # shared WAL SQLite checkpoints
  work/<source>/...                 # expendable extraction/index work, retained audits
  work/*.log, work/*report*.json     # logs and verification evidence
```

Some sources have additional raw layouts: geoBoundaries stores full-commit ZIPs,
per-layer pins and `inventory-resolved.json`; GeoNames uses per-file pin directories
inside its dated snapshot. OSM retains verified extracted SHP/SHX/DBF/PRJ and the
publisher README under `raw/`. No cleanup step removes raw files, even superseded
GeoNames partial downloads. Receipts (`*.download.json`) retain validators and hashes.

The source entry modules acquire data and dispatch normalization. `*_reader.py`
reads source formats and builds source-specific access structures; `*_rows.py`
(and `overture_areas.py`) maps records; `*_units.py` transforms bounded units;
`*_normalize.py` coordinates checkpoints; `*_report.py` checks source accounting.
Settings retain the original builder/policy identifiers and fingerprint inputs.
The shared modules provide:

- `runtime.py`: source ownership, geometry-worker lock, disk budgets and RSS.
- `geometry.py`: WGS84 bounds, polygon validation, explicit repair policies and
  component/bisection splitting without simplification.
- `writer.py`, `parquet.py`, `schemas.py`: bounded batching, atomic validated
  Parquet publication and the fixed Arrow contract.
- `artifacts.py`, `manifests.py`, `lifecycle.py`: immutable verification reports,
  one manifest format, verified resume, pruning and intermediate cleanup.
- `ledger.py`, `io.py`, `download.py`: concurrent checkpoints, durable file
  publication and pinned/resumable HTTP.

There is no adapter base class or registration framework.

## Manifest contract and the next stage

Every source writes **manifest version 2**, independently of **Arrow schema
version 1**. Fields are identical across sources:

```json
{
  "manifest_version": 2,
  "schema_version": "1",
  "source": "overture",
  "source_release": "2026-09-23.1",
  "configuration": {"builder": "overture-normalize-1", "policy": "..."},
  "inventory": {"path": "/absolute/.../inventory.json", "size": 123, "sha256": "..."},
  "inputs": [{"path": "/absolute/.../raw.parquet", "size": 123, "sha256": "..."}],
  "units": [{"stage": "overture.normalize", "unit_id": "object#row-group=0", "inputs_hash": "..."}],
  "partitions": [{"path": "/absolute/.../part.parquet", "kind": "areas", "rows": 100, "size": 123, "sha256": "..."}],
  "rows": {"areas": 100},
  "bytes": 123,
  "auxiliary": [{"path": "/absolute/.../verification-<hash>.json", "size": 123, "sha256": "..."}]
}
```

The example shortens hashes/configuration and uses illustrative sizes. `inputs`
are retained raw dependencies; `auxiliary` contains immutable reports, rejection
audits and required code maps. Expendable intermediate indexes and large TSVs
are not dependencies of completed normalized output. Paths are absolute; moving
an existing workspace requires deliberately rebasing manifests and checkpoint
paths, or rebuilding in the new location.

Consumers must use this shared function, exported from `build_data.acquire`:

```python
from build_data.acquire import Workspace, current_partitions

for path in current_partitions(Workspace(), "overture", "areas"):
    # Open one bounded file, or iterate its row groups.
    ...
```

`current_partitions(workspace, source, kind) -> tuple[Path, ...]` verifies the
manifest commit, frozen inventory/release, raw dependencies, auxiliary hashes,
unit fingerprints, output hashes and row counts before returning any paths.
Unknown kinds, missing/corrupt files or uncommitted manifests fail explicitly.
Never glob a normalized directory: an interrupted run can leave unpublished
files or files from older fingerprints.

Publishing verifies every unit and its Parquet schema/footer before atomically
writing the manifest, then commits its hash as `<source>.manifest/current` in the
ledger. A crash between these steps leaves an uncommitted manifest, which readers
reject. Only after that verification does pruning remove unlisted Parquet and
abandoned normalized `.part` files. Verification reports and raw files remain.
Legacy manifests take the normal per-unit verification path once; their existing
fingerprints and Parquet are reused, and their metadata becomes version 2.

## Resume, failures and cleanup

Each source has one advisory lock covering both download and normalization.
Polygon normalizers also hold the shared geometry lock; a competing owner fails
clearly. SQLite initialization retries only BUSY/LOCKED errors with a bounded
30-second deadline, using a fresh connection on retry. Transactions use WAL,
FULL synchronous mode and the same busy timeout. Separate processes can commit
different units concurrently; no source carries a private ledger retry loop.

Downloads freeze URLs, release, size, ETag/Last-Modified, retrieval time and
licences. SHA256s identify locally verified bytes; absent publisher checksums,
they do not establish publisher authentication. ZIP CRCs, Parquet footers and
source counts provide additional integrity checks. Downloads preserve partial
bodies and use Range/If-Range to resume; changed validators cannot append bytes
from another snapshot. GeoNames can pin a new path after daily rollover while
preserving superseded partial evidence. Other pin changes fail for review.

Unit identities remain source-specific: OSM bounded SHX spatial buckets,
Overture object/row-group pairs, GeoNames complete-line byte intervals, and
geoBoundaries country/level layers. Fingerprints retain source hashes, versions,
policy and relevant schema/library/partition settings. A unit is complete only
after every output is validated, atomically published, fsynced and hashed into
the ledger. Every rejection or repair is counted in the unit and final reports;
writer failures fail the unit instead of being misclassified as source rejects.

A verified current manifest with matching configuration skips extraction,
indexing and transformation as well as partition writing. Completed downloads
reuse that manifest's verified raw dependency records. Repeating `all` still
performs integrity I/O, but does not re-download, normalize or rewrite reports.
If an output is corrupt, only unfinished/corrupt units are transformed; deleted
access indexes or extracted text may need rebuilding to access those units.
A configuration/input change resumes using the original per-unit fingerprints,
so unaffected work remains reusable. An interrupted run never publishes a
partial new manifest or prunes the previous current output.

After successful manifest verification, cleanup removes GeoNames' large extracted
`allCountries.txt` and `alternateNamesV2.txt` plus its lookup database, Overture's
entity database, and geoBoundaries' extracted layer shapes. Small code maps,
extraction reports, rejection JSONL, unit reports, logs and the ledger remain.
OSM's spatial access index is retained as a verified auxiliary artifact.

## Schema and resource bounds

`SCHEMAS["areas"|"places"|"names"]` fixes ordered fields, types and nullability.
All rows carry source-scoped opaque string IDs, `source_release`, `license`, and
JSON `provenance` with nonempty `source_url`, `license_url`, `attribution`.
Provenance preserves raw names/attributes, hierarchy, upstream evidence,
retrieval/represented dates, repair/split details and original identities.

Areas are valid, nonempty 2D Polygon/MultiPolygon WKB in EPSG:4326, x/longitude
first, with actual finite xmin/ymin/xmax/ymax bounds. Splits preserve source and
entity IDs and carry a part ordinal. Overture names join through `entity_id`,
not the division-area record ID. Preserve territorial/land variants and source
roles. OSM overlapping split edges are not automatically coastline; reconciliation
must remove interior split boundaries and handle seam/polar closure separately.

Unknown optional values are null. Names use NFC and normalized whitespace;
English requires explicit language evidence, never an ASCII inference. Preserve
alias language tags, flags and raw validity intervals. Country codes use ISO
alpha-2 plus XK; GeoNames admin codes remain source codes, not ISO subdivisions.
Population zero differs from unknown. GeoNames P rows are settlements; A rows
retain administrative roles. Source eligibility, global uniqueness, foreign keys
and hierarchy checks are performed by adapters and reported separately from
structural schema validation.

Every adapter buffers rows through `PartitionWriter`, which preserves the original
source-specific batching targets and delegates to `write_partition`. Validation
runs before ledger completion and before atomic Parquet replacement. Hard limits:
8 MB per row, 32 MB per batch/row group, and 128 MB per file on disk, summed
uncompressed row-group bytes, and decoded Arrow data. Parquet uses zstd with
plain values; dictionary/delta encodings are rejected before decoding. Large
geometries are split by components and bounded bbox intersections, preserving
holes and area; oversized raw shapes that cannot be safely read are audited.

Admission checks preserve 20 GB free and cap the whole workspace at 45 GB
(decimal). Source caps are OSM 8 GB, Overture 25 GB, GeoNames 10 GB and
geoBoundaries 12 GB. Run world stages sequentially as the CLI does. RSS/timing are
recorded; admission checks are not reservations or a process-tree memory limit.
There is no global GeoDataFrame or whole-dataset Parquet read.

## Regenerate and verify

From an empty destination:

```sh
uv sync
uv run python -m build_data.acquire all --data-dir /path/to/new-data
uv run python -m build_data.acquire status --data-dir /path/to/new-data
uv run python -m build_data.acquire all --data-dir /path/to/new-data  # verified no-op
```

Use a fresh directory to keep existing downloads safe. Overture, GeoNames and
geoBoundaries discover and freeze their inventories on their first download;
new upstream releases can therefore produce different counts. OSM has explicit
release/size/validator constants in `osm_land.py`: if its mutable service no longer
serves that pin, acquisition fails rather than accepting changed data. Choosing a
new OSM snapshot requires deliberately updating those pins. Exact reproduction of
the table above requires preserving its pinned raw snapshots and inventories;
rerunning normalization reuses them offline. Do not erase hours of downloads to
reset checkpoints. Semantic changes require an intentional builder/policy bump.

Repository checks:

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy
```

Mypy is strict for the whole repository. Tests use synthetic inputs and loopback
HTTP servers only. The root autouse network guard blocks external DNS, TCP
connect/connect_ex and UDP destinations, including the real OSM download URL;
there is no acquisition-specific override that enables outside networking.

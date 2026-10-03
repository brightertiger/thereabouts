# Source acquisition pipeline

> Historical build record. These commands describe the old builders; use
> [the current pipeline guide](../DATA_PIPELINE.md) for inspection and migration.
> The protected workspace is not a target for rebuilding.

The four primary adapters acquire pinned raw inputs and publish validated,
bounded Parquet for [DATA_PLAN.md](../DATA_PLAN.md). Reconciliation and H3 building
are separate stages for the primary sources. The seven additional lookup adapters
below also produce their H3 keys during acquisition. Acquisition retains source identities, naming evidence,
administrative roles and provenance; it does not decide which source wins.

The separate [`plates` source](../PLATES.md) acquires vehicle registration evidence:
a country/territory survey, geographic code associations and plate-format rules.
It uses pinned Wikipedia revisions, Wikidata responses and reusable official
lists. Its three Parquet kinds deliberately have no H3 keys or golden-place joins.
Run `python -m build_data.acquire plates --data-dir data`; its raw snapshots,
licences, partial coverage and offline regeneration procedure are documented in
[PLATES.md](../PLATES.md).

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
keys include `osm_land`, `overture`, `geonames`, `geoboundaries` and the additional
lookups listed below; `--stage` defaults to
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

## Additional H3 lookup sources

Run only these adapters when sharing the data directory with reconciliation:

```sh
LOOKUP_DATA=/Users/ujjwal/Downloads/solo/thereabouts/data
for source in postal codes airports unlocode timezones phone dbip; do
  uv run --no-sync python -m build_data.acquire "$source" --data-dir "$LOOKUP_DATA"
done
uv run --no-sync python -m build_data.acquire status --data-dir "$LOOKUP_DATA"
uv run --no-sync python -m build_data.acquire.lookup_verify --data-dir "$LOOKUP_DATA"
```

Repeat the loop for a fully verified no-work run. `--stage download` and
`--stage normalize` work separately. Downloads can run detached with stdout/stderr
redirected to `work/<source>-extra-download.log`; normalizers use the matching
`*-extra-normalize.log`. Each source owns its own advisory lock and shares the
existing checkpoint ledger. Do not run `all` merely to repeat these seven sources:
`all` also dispatches the four primary sources.

The reviewed pins are in `lookup_catalog.py`; inventories freeze HTTP validators,
byte sizes, source URLs, licensing and retrieval dates before transferring bytes.
The one-byte GET probe verifies Range support, including DB-IP's endpoint, which
rejects HEAD requests. Git URLs use full commits; all 226 libphonenumber files
also verify against their Git blob hashes. DB-IP's advertised MD5 is for the
**decompressed CSV**, not its `.gz` transport. Raw ZIP CRCs and compressed-stream
checksums are verified. A changed remote validator fails while preserving the
partial file; choose a new inventory deliberately rather than mixing snapshots.
The October 2026 DB-IP pin is intentional; updating months requires a new pin.
GeoNames country/admin references are copied from the verified existing snapshot
when available, otherwise downloaded. Their original directories are read only.

| Source key | Download / pinned edition | Normalized contribution | Licence |
| --- | --- | --- | --- |
| `postal` | GeoNames `allCountries.zip`, `GB_full.csv.zip`, `NL_full.csv.zip`, `CA_full.csv.zip`, README; 2026-10-01 | 5,036,067 postal observations | CC BY 4.0; GB also retains the Royal Mail copyright/database-right 2022 notice |
| `codes` | DataHub `2e9d6498…` (2026-10-01), pycountry `4c6a6992…` (2026-02-18), existing GeoNames reference files | 252 countries; 5,046 ISO subdivisions; 3,865 GeoNames admin1 codes | PDDL 1.0 + GeoNames CC BY 4.0; iso-codes/pycountry LGPL 2.1 or later |
| `airports` | OurAirports CSV, 2026-10-01 | 86,154 airports, including closed sites and heliports | Public domain |
| `unlocode` | DataHub `b1309b37…` (2026-07-27); package identifies data as **2024.2.0** | 116,213 locations; 92,874 located | PDDL 1.0, UNECE/DataHub attribution retained |
| `timezones` | timezone-boundary-builder **2026d with oceans**, IANA **2026e** | 444 zones; 4,567,490 compact memberships; 821 IANA rows | ODbL 1.0 / OpenStreetMap attribution; IANA tables public domain |
| `phone` | libphonenumber `0ae309f1…` (2026-09-24), all geographic-description languages | 254 territory/service metadata entries; 427,963 prefix descriptions | Apache 2.0 |
| `dbip` | DB-IP Lite City **2026-10**, CSV gzip, IPv4 + IPv6 | 7,786,864 ranges: 3,620,434 IPv4 + 4,166,430 IPv6 | CC BY 4.0; “IP Geolocation by DB-IP” with https://db-ip.com attribution |

Upstream source/licence evidence: [GeoNames postal README](https://download.geonames.org/export/zip/),
[OurAirports data](https://ourairports.com/data/),
[DataHub country codes](https://github.com/datasets/country-codes),
[pycountry](https://github.com/pycountry/pycountry),
[DataHub UN/LOCODE](https://github.com/datasets/un-locode),
[timezone-boundary-builder](https://github.com/evansiroky/timezone-boundary-builder),
[IANA](https://www.iana.org/time-zones),
[libphonenumber](https://github.com/google/libphonenumber),
[DB-IP Lite](https://db-ip.com/db/download/ip-to-city-lite).
UNECE's direct download endpoint returned HTTP 403, so UN/LOCODE uses the openly
licensed mirror above; it is older than UNECE's advertised 2025-1 release.
DataHub's country-code README includes its upstream standards-rights caveat and
is retained verbatim. No licence is inferred from a GitHub repository's visibility.

### Verified extra-source snapshot (2026-10-02 IST)

All seven new sources report download and normalization **complete**. Structural
rejects are zero for each source. Every stored H3 index and point/cell agreement
was validated during atomic Parquet publication; the final verification rechecked
all manifest, input and output hashes. A second run performed no acquisition,
normalization or report rewriting: **5,011 raw/normalized files** retained exactly
the same sizes and modification times. Evidence is in
`work/extra-lookups-rerun.json` and `work/extra-lookups-verification.json`.

| Source | Retained raw bytes | Normalized Parquet bytes |
| --- | ---: | ---: |
| Postal | 44,700,758 | 188,037,213 |
| Codes | 843,631 | 487,677 |
| Airports | 12,734,002 | 10,212,926 |
| UN/LOCODE | 7,297,966 | 9,191,072 |
| Timezones | 89,226,948 | 179,887,498 |
| Phone | 12,194,851 | 10,360,961 |
| DB-IP | 85,827,400 | 360,258,499 |

The additional sources, receipts, manifests and audits occupy **1,013,898,554
bytes**; task logs/reports add about 0.18 MB. This excludes the pre-existing shared
ledger and environment. The largest measured normalization RSS was **240,549,888
bytes** (timezones). No task process remains detached after completion.

Publisher comparisons: OurAirports' published 86,154-airport count matches;
pycountry's documented 5,046 subdivisions match; all 444 timezone names in the
release's names JSON match; DB-IP's 7,786,864 rows and decompressed CSV MD5 match.
Postal inputs have no independent published row total: streamed counts are
1,826,904 base rows + 900,676 CA + 1,839,678 GB + 468,809 NL. Phone normalization
accounts for every data line in the 224 pinned geographic-prefix files plus all
254 XML territories/services; comments are format metadata. The mirror's 116,213
UN/LOCODE rows are accounted for, but equivalence to newer UNECE 2025-1 is unverified.

Spot checks: US `10001` -> `882a100d25fffff` in Manhattan; BLR ->
`8860169047fffff`, JFK -> `882a103b15fffff`, both matching their source coordinates.
Bengaluru's `(12.9716,77.5946)` cell `8860145b49fffff` maps to `Asia/Kolkata`;
New York's `(40.7128,-74.0060)` cell `882a107289fffff` maps to `America/New_York`.
The ocean point `(0,-150)` maps to `Etc/GMT+10`. `8.8.8.8` is in
`8.8.8.0–8.8.8.255`, US / Mountain View, cell `8828347509fffff`.

**Upstream postal discrepancy:** all nine GeoNames `IN/560001` observations name
Bengaluru but supply `(13.2257,77.575)`, cell `8860169523fffff`, about 28 km north
of central Bengaluru. The requested central-Bengaluru spot check therefore fails.
These original coordinates, names and accuracy values are retained, and the
verifier records the discrepancy as a data-quality finding; it does not invent a
correction or label that check passed. A wrong stored H3 key remains a hard error.

The timezone interval audit covers all **691,776,122** valid resolution-8 cells,
with **zero gaps** and 2,021,513 additional memberships from source overlaps.
There are no zones without resolution-8 centers and no geometry repairs/rejects.
These are cell-center coverage results, not a claim of exact boundary accuracy.

Repository validation: `uv run --no-sync pytest` (184 passed, 7 existing skips),
`uv run --no-sync ruff check`, `uv run --no-sync ruff format --check`, and
`uv run --no-sync mypy`. Tests are synthetic and external networking remains
blocked by the existing test guard.

### Lookup schemas and cleaning

All new kinds use the existing manifest-v2 contract and bounded Parquet writer.
They add `lookup_schema_version=1` and `h3_reference_resolution=8` metadata;
the original `areas`, `places`, `names` schema bytes and fingerprints are unchanged.
Every row has the existing source identity, release, licence and JSON provenance
fields. Provenance contains raw evidence, source and licence URLs, attribution,
and retrieval time. Per-source `licenses-<inventory hash>.json` files are manifest
auxiliaries. Distribute those notices with the derived tables.

| Kind | Join keys and additional fields |
| --- | --- |
| `postal_codes` | Country + postal code + source variant; place, admin1/2/3 names/codes, original accuracy value; point/H3 fields |
| `countries` | `country_code` alpha-2; alpha3, zero-padded ISO numeric/M49, UN region/subregion/intermediate codes and names, calling code, currency, languages, TLD, continent |
| `subdivisions` | `(code_system, code)` distinguishes ISO-3166-2 from GeoNames-admin1; country, name/type, parent code, GeoNames ID and ASCII name where supplied |
| `airports` | OurAirports `ident`, IATA/ICAO/GPS/local codes, type, municipality, country/region; point/H3 fields |
| `trade_locations` | `locode`, country/location components, original function flags, subdivision, names, status, IATA, date/change/remarks; point/H3 fields |
| `timezones` | `(tzid, part)`; valid WGS84 longitude-first WKB geometry and ocean indicator; large geometry parts split without simplification |
| `timezone_cells` | `(h3, tzid)` membership, `h3_uint64`, actual `h3_resolution` from 0 through 8; geometry joins on `tzid` |
| `zone_tables` | IANA `zone.tab`, `zone1970.tab`, `zonenow.tab`; zone, country associations, comments and original representative coordinates plus point/H3 fields |
| `phone_metadata` | Territory (including non-geographical service code `001`) + country calling code; dialing prefixes, leading digits and metadata XML |
| `phone_prefixes` | `(prefix, language)`; calling code, description, list of candidate territory codes |
| `ip_ranges` | Inclusive start/end addresses, address family, 16-byte big-endian packed bounds (IPv4 left padded), country/region/city; point/H3 fields |

Point/H3 fields are `latitude`, `longitude`, canonical lowercase `h3`,
`h3_uint64: uint64` and `h3_resolution=8`. Unknown coordinates remain null;
malformed coordinates retain the record, raw values and `coordinate_error` in
provenance. They are counted separately from structural rejects. The UN/LOCODE
snapshot has 23,339 unlocated rows, including 278 invalid coordinate strings
(e.g. minutes >= 60). No guessed decimal-degree conversion is applied.
DB-IP's source sentinel `ZZ` and supplied `(0,0)` remain as published, with raw
provenance; an H3 key does not make a geolocation estimate authoritative.

Postal partial and full variants coexist, preserving duplicate code/place
observations. Consumers choose their preferred variant. GeoNames' additional
country entries remain alongside the 249 ISO countries. Phone descriptions keep
all 224 localized files; shared calling codes retain all candidate territories
instead of inventing a unique country or geocoding their text. Prefixes have no
H3 field; use longest-prefix matching and language selection in a later linker.

Timezone cells represent **resolution-8 cell-center membership** in the source
polygons. Interiors are stored as compacted ancestors; only boundary regions need
fine cells. H3 logical descendants are not geometrically contained in the parent
hexagon: the implementation uses conservative spherical child envelopes based
on H3's maximum-edge bounds, then tests the original polygon at the finest level.
It handles holes, poles and longitude wrap, and compacts complete sibling sets,
including pentagons. Tests compare against exhaustive fine-cell membership.
To look up a resolution-8 cell, compute its nine ancestors (resolutions 0..8) and
join their keys to `timezone_cells`; no geometry test or global expansion is needed.
This uses the builder's full historical zone IDs, not its merged `now` variant.
Ocean `Etc/GMT±N` polygons are included as supplied (IANA's sign convention is
reversed); source overlaps remain potentially multiple results. Near a boundary,
a cell's center may differ from an arbitrary point in that cell. Geometry remains
available for later exact-boundary handling. IANA table dates can be newer than
the boundary release and do not silently relabel the polygons.

Text normalization checkpoints at 10,000 input records and timezones checkpoint
per zone. No global dataframe or decompressed postal/IP file is built. All seven
sources together have an additional 6 GB disk admission cap. The original global
45 GB workspace cap and 20 GB free-space reserve still apply. Row, batch and file
bounds remain 8/32/128 MB. Temporary timezone shapefiles are removed only after
manifest verification; a verified rerun skips extraction and transformation.
`lookup_verify` validates manifests, source accounting and named spot checks,
then measures global timezone coverage with dense descendant-rank intervals,
without expanding hundreds of millions of fine cells. Its report is
`work/extra-lookups-verification.json`.

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

Admission checks preserve 12 GB free and cap the whole workspace at 60 GB
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

## Raw offload and restore

Raw custody is explicit and independent of normalized completion. The acquisition
CLI supports a non-destructive transfer and an already-verified-transfer record:

```sh
PIPELINE_DATA=/Users/ujjwal/Downloads/solo/thereabouts/data
uv run --no-sync python -m build_data.acquire offload \
  --sources osm_land overture geonames geoboundaries \
  --remote gs://pyofflinegeocoder-summer-sector-488705-m8/raw \
  --record-existing --data-dir "$PIPELINE_DATA"
uv run --no-sync python -m build_data.acquire status --data-dir "$PIPELINE_DATA"
uv run --no-sync python -m build_data.acquire restore \
  --sources overture --data-dir "$PIPELINE_DATA"
```

`offload` without `--record-existing` first verifies the local snapshot and runs
`gcloud storage rsync --recursive <raw/source> <remote/source>`. Neither command
deletes files. `--record-existing` records the operator's prior verification of
remote file count and bytes; it does not pretend to have rechecked remote hashes.
The source-scoped `work/offloaded/<source>.json` binds custody to the exact current
normalized manifest and records the destination and evidence. The four original
sources were recorded this way after their verified external transfer.

`status` reports matching records as **offloaded**. `all`, or a source CLI command,
verifies and reuses its completed normalized outputs without downloading those
raw files. A missing/corrupt normalized output fails explicitly and requires
restoration before rebuilding. `current_partitions` still verifies local inputs,
auxiliary evidence, normalized checkpoints and hashes; only missing raw files
covered by the exact offload record are allowed. Present but corrupt raw files
are never excused. A changed manifest does not inherit a stale offload exemption.

`restore` runs `gcloud storage rsync --recursive <recorded-remote> <raw/source>`,
then verifies every pinned raw dependency and normalized artifact before clearing
the offloaded marker. Interrupted/failed restores leave that marker intact.
Existing resource guards still apply to restore admission. Keep small inventories,
receipts and licence notices available locally for status and provenance.

## Golden H3 dataset

This is the lower-level base-cell stage. Use the full controller documented
below for the current normalized dataset. The standalone commands here target
a separate workspace with acquired/reconciled inputs, not an active v2 symlink.

`build_data.golden` consumes canonical country checkpoints as they become ready,
without waiting for a new reconciled world manifest. It exports canonical places,
timezone memberships and code/phone links first. It then builds resolution-3 H3
blocks whose actual r8 descendant envelopes touch only completed countries, using
the reconciled lookup and conservative certificates. Postal, airport, trade and
IP rows join their existing r8 key through the resulting compact cell table.
Pending, unlocated, ineligible and unresolved rows remain distinguishable.

```sh
GOLDEN_DATA=/path/to/base-stage-data
uv run --no-sync python -m build_data.golden pilot --countries BE NL LU CA --workers 2 --data-dir "$GOLDEN_DATA"
uv run --no-sync python -m build_data.golden run --workers 2 --watch --data-dir "$GOLDEN_DATA"
uv run --no-sync python -m build_data.golden status --data-dir "$GOLDEN_DATA"
```

Outputs are Parquet beneath `golden/`, with `manifest.json`, `quality.json`,
`DATA_LICENSES.md` and `DATASET_CARD.md`. The shared ledger owns `golden.*`
checkpoints; `work/golden/run.json` records progress. Use the manifest's completion
flag and table inventory, never an unrestricted glob. The full layout, all columns,
certificate argument, checks and resumption commands are in
[GOLDEN_DATASET.md](golden-dataset.md). No new raw downloads are required.


### Disk-neutral golden v1 replacement

The v1 reconciliation rebuild replaces one verified country at a time and deletes
that country's superseded SQLite file and extract/link intermediates immediately.
The acquisition manifests and normalized sources remain immutable. The old
reconciled manifest is archived under `work/reconcile/history/`; the active
manifest is explicitly incomplete while the new generation builds. A verified
country resumes without reconstructing its retired intermediates.

The original v1 results and retirement mechanism are historical records in
[GOLDEN_V1.md](base-cell-results.md). The current rebuild controller below reuses verified
reconciliation and base-cell checkpoints; city normalization never retires or
modifies reconciled inputs.

## Acquired sources to normalized golden data

The 2026-10-02 world v2 run is verified and locally active. `data/golden` resolves
to `data/golden-v2`; the retained v1 directory is `data/golden-v1`. Full measured
results and limitations are in [GOLDEN_V2.md](city-normalization-results.md).

`uv run --no-sync python -m build_data.acquire ghsl` acquires the pinned
GHS-UCDB R2024A V1.2 general-characteristics ZIP (6,902,089 bytes, SHA256
`bc879d82320504f89df2041b7936221c8239cd808abe93980493aed062b4f3d6`). It validates
the ZIP and GeoPackage, converts the declared Mollweide geometry to WGS84, and
publishes 11,422 `areas` rows through the common bounded writer, ledger and
manifest-v2 contract. Licence: CC BY 4.0, European Commission/JRC; the manifest
retains attribution and the GHSL reference publication. This is a built-up urban
extent source, not municipal boundaries. See the [producer overview](https://human-settlement.emergency.copernicus.eu/ucdb2024Overview.php)
and [attribution requirements](https://human-settlement.emergency.copernicus.eu/GHSLhowToCite.php).

The single controller is `build_data.rebuild_golden`. Its chain is acquisition →
reconciliation → base cells (`build_data.golden`) → canonical cities/maps
(`build_data.cities`) → normalized cells, joins and verification
(`build_data.normalize_cells`) → optional local activation. Packages name jobs;
`golden-1` and `golden-2` are dataset schemas.

```sh
uv sync --frozen
uv run --no-sync python -m build_data.rebuild_golden --data-dir data --through pilot
# After examining the generated pilot, bind the reasoned decision to its hashes:
uv run --no-sync python -m build_data.normalize_cells review --data-dir data \
  --review docs/city-normalization-pilot-review.json --gate data/work/v2-pilot/gate.json
nohup uv run --no-sync python -m build_data.rebuild_golden --data-dir data \
  --through world > data/work/v2-world.log 2>&1 < /dev/null &
```

The committed `docs/city-normalization-pilot-review.json` records the examined
exceptions for this pinned snapshot. It is evaluation evidence, never an input
to city assignment. The review command binds it to freshly verified artifacts
and rejects changed loss counts or destinations; inspect new source editions
before issuing a new receipt.

Use the same controller command to resume any interrupted stage. From an empty
workspace it acquires all sources, runs the reconciliation pilot and world,
builds base cells, then evaluates the city pilot. Exact source-date reproduction
requires the preserved acquired snapshots; fresh discovery may retrieve newer
GeoNames bytes. Existing verified acquisition/reconciliation checkpoints are reused
without restoring offloaded raw files. `--sample-gate` can additionally require
the historical reconciliation improvement gate.

The base stage's complete tables are verified against reconciled inputs and cell
code, then hard-linked into `base_cells/<digest>/`. `base_cells/current.json`
points to that committed manifest. It is an explicit immutable dependency, not
an assumption that the active `golden/` directory happens to contain v1.
Normalization builds `golden-v2/` beside the active dataset. Country indexes/maps,
cell blocks, refreshed joins and country quality each have input/code/policy
checkpoints. The base snapshot's hard links add no duplicate payload bytes.

Logs and controller state are under `work/rebuild/`; world progress also lives in
`work/v2-run.json`. `--through world` stops only after final stored-cell quality and
integrity verification. Examined individual boundary losses can be supplied with
`--review`; each exception must match the exact city, count and destinations.
`--through publish` activates the verified result locally through a stable symlink
and retains the prior directory as `golden-v1/`. No external publication is done.
See [GOLDEN_V2.md](city-normalization-results.md) for measured results, gate receipts, all-boundaries
checks, split-isolated scoring, and known limitations.

Final boundary reviews are bound to the incomplete output manifest, including
its absolute artifact paths. A clean machine must bind its own receipt after
examining `golden-v2/quality.json`; it cannot reuse another machine's manifest
fingerprint. For the same pinned sources, the committed pilot review supplies
the two already-examined source-overlap exceptions. The final verifier checks
their boundary IDs, counts and destinations against the new report:

```sh
uv run --no-sync python - <<'PY'
from pathlib import Path
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, write_json

output = Path("data/golden-v2")
notes = read_json(Path("docs/city-normalization-pilot-review.json"))
write_json(Path("data/work/v2-world-review.json"), {
    "manifest": fingerprint(read_json(output / "manifest.json")),
    "boundary_exceptions": notes["boundary_exceptions"],
})
PY
uv run --no-sync python -m build_data.rebuild_golden --data-dir data \
  --through world --review data/work/v2-world-review.json
```

This receipt records a review; it changes no city assignment. If source editions
produce additional losses, inspect them before adding any further exception.

### Rebuilding for a content-neutral rename

The controller accepts `--through base` to stop after a newly guarded base is
built and snapshotted, before pilot or evaluation work. Record logical contents
with `python -m build_data.digest_golden` before rebuilding, and compare the
regenerated base with `--compare` before continuing to the normalized world.
Use a separate `--output` directory and preserve the old datasets until both
comparisons and ordinary verification succeed.

For a controlled rebuild with unchanged city policy, inputs and normalization
code, `--reuse-development` retains the existing `data/work/v2-dev.json` verbatim
and skips development scoring. It requires that report to exist; it does not
skip pilot measurements, stored probe blocks, review gates or world verification.
Use this option on every controller invocation after `--through base` when the
completed evaluation must not be scored again. The retained report is historical
evidence, not a newly executed score. The holdout is never a controller stage.

Acquisition configurations have separate schema dependencies: original geographic
sources use the area/place/name contracts; existing lookups use their lookup
contracts; plates uses its own three contracts. Adding a standalone source does
not invalidate unrelated acquired data. Changes to a family's existing contracts
still invalidate that family's checkpoints.

The digest command sorts the same SHA256 row values in 250,000-row disk runs,
with at most 64 input runs per merge. This keeps scratch access sequential on
small machines; schema descriptors, row encoding, duplicate counts and the final
hash format are unchanged from its original SQLite sorter. Scratch is disposable
and separate from the pipeline ledger. Each logical table's scratch is removed
after its digest completes.

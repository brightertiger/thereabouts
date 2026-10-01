# Golden dataset (schema `golden-1`)

V1 changes and measured rebuild status: [GOLDEN_V1.md](GOLDEN_V1.md). The historical pilot measurements below describe v0.

The golden stage consumes committed reconciliation country checkpoints and acquired
lookup manifests. It writes only beneath the supplied data directory. The H3
reference key is **resolution 8**. A row's original coordinates are retained, but
its place assignment is the answer at its H3 cell's centre. These can differ near
boundaries. Countries and cities inherit the reconciliation policy, without new
name, boundary, or nearest-city overrides.

## Run and resume

```sh
GOLDEN_DATA=/Users/ujjwal/Downloads/solo/PyOfflineGeocoder/data
uv run --no-sync python -m build_data.golden static --data-dir "$GOLDEN_DATA"
uv run --no-sync python -m build_data.golden pilot --countries BE NL LU CA --workers 2 --data-dir "$GOLDEN_DATA"
uv run --no-sync python -m build_data.golden run --workers 2 --watch --data-dir "$GOLDEN_DATA"
uv run --no-sync python -m build_data.golden status --data-dir "$GOLDEN_DATA"
```

`pilot` defaults to blocks whose conservative dependencies include BE, NL, LU or
AU. The command above selects Benelux and Canada, whose dependencies were ready
when the pilot ran. It exhaustively compares all resolution-8 centres with
direct vector labelling,
checks every ancestor lookup, and compares 16 evenly spaced centres in each block
with the independent scalar reconciliation oracle. The synthetic test region
additionally compares **every** fine centre against that independent scalar oracle.
`--verify-blocks` enables the same exhaustive checks for another run.

`plan` caches the actual finest-centre envelope of every resolution-3 root.
`--countries CC ...` selects country-dependent blocks; `--limit-blocks N` bounds a
run. `lookups` refreshes joins and checks from existing committed cells without
building more cells. `--watch` refreshes country availability after each complete
pass, sleeping 300 seconds by default. A single golden lock prevents overlapping
controllers. One or two worker processes own different blocks; two blocks at most
are in flight. Reconciliation's lock, code and working files are untouched.

The completed marker is `work/golden/run.json` with `completed: true`, together
with a committed `golden/manifest.json` also having `completed: true`. Individual
country and cell checkpoints are useful before then. `status` does not build or
hash tables. The same command safely resumes verified units, rebuilds corrupt
outputs, and fills pending lookup joins when more cells exist. An interrupted
Parquet write cannot complete its ledger unit. Do not infer completion from a
process exiting, a log line, or the existence of a Parquet file.

The golden stage has an 8 GB logical disk cap for `golden/` plus `work/golden/`.
It preserves 13 GB free. For this run, acquisition/reconciliation was externally
configured with a 12 GB reserve; golden does not modify that setting. Temporary joins have a 512 MB memory limit and a 512 MB spill cap.
A resource guard stops new units; `--watch` reports `waiting for disk` and retries
after the polling interval. Other I/O failures remain visible failures. The stage
never deletes another stage's data. Source
raw custody is described in [DATA_PIPELINE.md](DATA_PIPELINE.md#raw-offload-and-restore).

## Layout and manifest

```text
golden/
  manifest.json                  # sole published table inventory and input hashes
  quality.json                   # counts, coverage, disagreements and checks
  DATA_LICENSES.md                # source attribution and licence summary draft
  DATASET_CARD.md                 # limitations and intended-use draft
  places/<CC>.parquet
  cells/<resolution-3-root>.parquet
  lookups/<spatial-kind>/joined.parquet
  lookups/<static-kind>/<source-partition>.parquet
work/golden/
  countries.json                 # expected countries and source component envelopes
  blocks.sqlite                  # reusable finest-centre envelopes; hashed dependencies
  run.json, pilot.json            # progress and pilot evidence
work/ledger.sqlite3               # shared golden.* checkpoints
```

The manifest records schema version, reference/block resolution, source policy,
reconciliation and golden builders, country/land hashes and each table's absolute path, kind,
row count, bytes and SHA256. Cell records also name their resolution-3 block.
The manifest and its companion reports are committed as `golden.manifest/current`.
Only use its listed files, never glob for a supposedly complete snapshot. Running
updates replace files atomically; readers needing a stable verified snapshot
should wait for the controller to finish and verify manifest checksums.

Empty ocean blocks have a zero-row Parquet and a checkpoint. This distinguishes
known ineligibility from a block awaiting reconciliation. Empty files contribute
to the 41,162 real H3 resolution-3 blocks, including pentagons. No logical pentagon
padding addresses are treated as real cells.

## Places

Canonical `place_id` is the reconciliation identity, never a name-derived ID.
Country identities are `country:<CC>`; other identities retain role and source.
District entities are retained as well as countries, states and cities, preserving
the reconciled catalogue. JSON fields are serialized UTF-8 JSON, not pickles.
Unknown values are null. A population of zero remains distinct from null.

| Column | Type | Meaning |
| --- | --- | --- |
| `place_id` | string | Stable canonical identity, unique in the complete catalogue |
| `role` | string | `country`, `state`, `city`, or retained `district` |
| `name` | string | Reconciliation's preferred display name |
| `name_en` | string? | Preferred name only when its naming provenance explicitly identifies English |
| `local_name` | string? | Source's local/default name; not an inferred translation |
| `country_code` | string | ISO alpha-2, plus source/user-assigned codes such as XK |
| `code` | string? | Country or subdivision code actually known to reconciliation |
| `code_status` | string? | Source/code status, including `user-assigned` for XK |
| `parent_id` | string? | Canonical parent, null for countries |
| `parent_method` | string? | Evidence for a parent assignment when recorded |
| `sovereign_id` | string | `country:<sovereign_code>`; can await that country in a partial snapshot |
| `sovereign_code`, `sovereign_name` | string? | Recorded sovereign, otherwise the country itself; unknown name remains null |
| `population` | int64? | Reconciled population |
| `geonames_id` | string? | Linked GeoNames source identity |
| `geonames_admin1` | string? | GeoNames source admin1 code, not an ISO subdivision inference |
| `feature_code` | string? | Retained GeoNames/source classification |
| `source_subtype`, `settlement_class`, `city_exclusion` | string? | Source role/class and recorded reason for retaining an administrative unit outside city selection |
| `overture_ids` | list<string> | Overture identities on the canonical entity |
| `wikidata_ids` | list<string> | Known Wikidata IDs from source evidence and retained GeoNames links |
| `source_ids` | JSON string | Full source/identity list |
| `provenance` | JSON string | Naming/source evidence, release, licences and upstream attributes |
| `name_provenance` | JSON string | Chosen naming source and explicit language evidence |
| `link` | JSON string | Reconciliation's identity-link method/evidence or JSON null |

No aliases are erased from source provenance. This table does not manufacture ISO
codes, coordinates or translations for canonical entities lacking them.

## Cells

| Column | Type | Meaning |
| --- | --- | --- |
| `h3` | string | Canonical lowercase H3 hexadecimal key |
| `h3_uint64` | uint64 | Same H3 key as an unsigned integer |
| `h3_resolution` | uint8 | Stored resolution, between 3 and 8 inclusive |
| `country_id`, `state_id`, `city_id` | string? | Foreign keys to `places.place_id` |
| `country_method`, `state_method` | string? | `area` when assigned; null when absent |
| `city_method` | string? | `area`, `nearest`, or null |
| `land_method` | string | `land` or `offshore` |

Each eligible r8 centre has exactly one stored ancestor; ineligible ocean has
none. Eligible but unresolved land has a row with null place IDs. Fields and
methods must all be equal to collapse a subtree. Compaction stays within r3
checkpoint roots; this trades a few extra rows for independent resumption.

The builder reuses the original hierarchy traversal and conservative-certificate
approach. It enumerates every actual r8 descendant (including pentagon children),
then tests enclosing rectangles against unsimplified polygon boundaries, including
holes, overlaps and artificial source splits. A rectangle with no boundary crossing
has constant containing identities. Nearest-city certificates additionally require
the nearest/runner-up gap and inclusive 50 km cutoff to remain separated by a
spherical route-distance bound over the entire rectangle. Sea and offshore
uncertainty refines to r8. Equal labels are collapsed again after refinement.

Eligibility follows OSM land or the reconciliation's 1 km spherical offshore
projection. Land predicates use prepared polygons. For offshore candidates, each
short great-circle segment is enclosed by a spherical cap at its midpoint with
radius half its arc length. Length-bucketed cKDTrees query those caps enlarged by
the cutoff, so no segment within the cutoff can be missed. Candidate segments
still obey the scalar oracle's outward-rounded SQLite polygon bounds and seam
windows. Exact endpoint/segment projection follows the original equations.
Numerical ties, cutoff uncertainty, and projections extremely close to an
administrative edge use the scalar oracle. Land/country/state/city priorities and
same-country fallback are unchanged. No empirical H3 radius assumption is used.

A dependency envelope is expanded for every possible offshore projection and
checked against **all acquired country polygon component envelopes**, including
countries not yet reconciled. Any pending country makes the entire block wait.
The extra 1e-4 degree margin covers SQLite float32 R-tree rounding. At the date seam, actual descendant centres are split into disconnected western
and eastern envelopes; expanded windows wrap at ±180°. Certificates that cross
the seam or approach a pole refine to the finest centres.

`build_data.golden.reader.Cells` performs ancestor lookup. Never calculate a fresh
coarse cell from a coordinate: logical ancestry from the original r8 key is the
contract. Batched source joins use nonoverlapping integer descendant intervals,
which include harmless invalid-digit gaps but exactly the valid H3 descendants.
Distinct source keys join within r1 subtrees, bounding each interval sort to at
most 49 r3 blocks. An ASOF lower-endpoint match plus an upper-endpoint check
rejects gaps, then a key join restores every original source row, including duplicates.

## Shared lookup fields

All lookup kinds preserve acquisition's columns, types, rows and source order
semantics (physical output row order is not promised). Repeated source observations
remain repeated observations. The shared original fields are:

| Columns | Type | Meaning |
| --- | --- | --- |
| `source`, `source_id` | string | Adapter and source-scoped identity |
| `source_release`, `license`, `provenance` | string | Pinned release, exact licence label and JSON source evidence |
| `latitude`, `longitude` | float64? | Original WGS84 coordinates, where the kind has point fields |
| `h3`, `h3_uint64`, `h3_resolution` | string?, uint64?, uint8? | Original reference cell; located points are r8; timezone memberships can be coarser |

Postal codes, airports, trade locations and IP ranges add:

| Column | Type | Meaning |
| --- | --- | --- |
| `country_id`, `state_id`, `city_id` | string? | Assignment obtained from the compact `cells` table |
| `cell_country_code` | string? | Country derived from `country_id`; original `country_code` remains intact |
| `cell_status` | string | `matched`, `unassigned` eligible land, `ineligible` ocean, `pending` block, or `unlocated` source row |
| `country_disagrees` | bool? | Comparison of non-null source and spatial country codes; null when either side is unavailable |

The quality report counts true disagreements and the compared denominator.
Missing or pending assignments do not silently count as agreement. Reruns replace
pending joins once their cells are committed. Earlier pilot files may remain on
disk; the manifest lists only the current `joined.parquet` for each spatial kind. Source coordinates and source city
names are never silently corrected from spatial answers.

## Lookup tables and their other columns

Every name below is a directory beneath `lookups/`. All fields below are strings
unless another type is specified. Shared original fields above are present in
every table; point fields are present only where explicitly noted.

| Table | Other original columns and meanings |
| --- | --- |
| `postal_codes` | `country_code`, `postal_code`, `place_name`; `admin1_name`, `admin1_code`, `admin2_name`, `admin2_code`, `admin3_name`, `admin3_code` retain source administrative labels/codes; `accuracy` retains the source accuracy value; `variant` distinguishes base versus full postal editions. Includes point fields and spatial join fields. |
| `airports` | `ident`, `iata_code`, `icao_code`, `gps_code`, `local_code` are source identifiers; `type`, `name`, `municipality`, `country_code`, `region_code` preserve source classification, labels and codes. Includes closed sites/heliports, point fields and spatial join fields. |
| `trade_locations` | `locode`, `country_code`, `location`, `name`, `name_ascii`, `subdivision_code`; `function`, `status`, `iata_code`, `date`, `change`, `remarks`, `coordinates_raw` preserve UN/LOCODE evidence. Includes nullable point fields and spatial join fields. |
| `ip_ranges` | `ip_start`, `ip_end` are inclusive textual endpoints; `ip_version` is uint8 (4 or 6); `ip_start_packed`, `ip_end_packed` are 16-byte big-endian comparison keys (IPv4 left-padded with zero bytes); `country_code`, `region`, `city` retain DB-IP's own answer. Includes point fields and spatial join fields. |
| `timezone_cells` | `tzid` plus non-null H3 key fields: compact cell membership at the acquisition stage's r8 centre semantics, including oceans. Preserved byte-for-byte as hardlinks to verified immutable normalized files. This is an independent membership table and retains any source overlaps; it is not clipped to eligible land. |
| `zone_tables` | `table` identifies the IANA reference table; `tzid`, `country_codes`, `comments`, `coordinates_raw` preserve its values. Includes nullable point fields for the IANA reference coordinate. These are reference metadata, not spatial place assignments. |
| `countries` | `country_code`, `alpha3`, `numeric`, `name`, `calling_code`, `currency`, `languages`, `tld`, `continent`, `m49`, `region_code`, `region_name`, `subregion_code`, `subregion_name`, `intermediate_region_code`, `intermediate_region_name`: source country/code hierarchy and reference metadata. |
| `subdivisions` | `code`, `code_system`, `country_code`, `name`, `type`, `parent_code`, `geoname_id`, `name_ascii`: ISO or GeoNames subdivision metadata. GeoNames admin codes are never treated as ISO codes. |
| `phone_metadata` | `territory`, `calling_code`, `leading_digits`, `national_prefix`, `international_prefix`, `metadata_xml`: original libphonenumber territory/service metadata; non-geographic service territory 001 is retained. |
| `phone_prefixes` | `prefix`, `calling_code`, `language`, `description`, `country_codes` (list<string>): multilingual geographic descriptions and candidate country codes. Shared calling codes can refer to several countries. |

The four code/phone tables add `country_id` (string?, direct country-code match),
`place_id` (string?, unique target only), `place_ids` (list<string>, all code-derived
candidates), and `link_status` (`matched`, `ambiguous`, `unmatched`, `pending`).
Subdivisions first use explicit ISO codes or the reconciled GeoNames state
crosswalk, then administrative GeoNames identity or exact country-scoped aliases
of retained states/districts. Multiple matches remain ambiguous. `link_method`
records the evidence. Names never manufacture ISO codes on canonical places.
Phone prefixes narrow their supplied country codes with the pinned libphonenumber
fixed-line patterns and leading digits. A candidate survives if some full number
can extend the prefix; short shared prefixes remain ambiguous. Missing or
contradictory pattern evidence retains the original candidates. The original
`country_codes` column is unchanged; descriptions are not fuzzy-matched to cities. An ambiguous multi-country prefix has all candidate
IDs and a null singular ID. Missing reconciled countries remain pending.

## Quality and limitations

`quality.json` lists per-table rows and bytes, lookup status/disagreement counts,
blocks built/waiting/remaining, stored cells per resolution and represented finest
centres. Its checks repeat every named fixture from `RECONCILIATION.md` through
`cells`, the sixteen additional metropolitan probes in `probes.json`, and every
GeoNames P observation at population >=15,000. Pending blocks
remain counted in the total and have an explicit pending count. State/city
comparisons retain the original definitions, including PPLX/historical observations
and the distinction between same identity and containing another city.

The integrity report counts duplicate canonical IDs and missing cell, parent and
sovereign references. Partial snapshots can lack a sovereign country still being
reconciled. Dataset completion requires unique canonical IDs and no dangling cell, parent
or sovereign place IDs. Country catalogue records can exist without assigning a
spatial country polygon, as for Western Sahara under the selected perspective. Source agreement is not independent accuracy. Country/state/city name
conventions, broad municipalities and unlinked locality limitations remain those
of reconciliation. Quantization from the source coordinate to the r8 centre can
change even a named fixture. Such results are reported, never patched by name.

The licence summary and dataset card are drafts. Original licences and evidence
remain attached; consult the retained per-source notices when preparing release.

## Measured pilot (2026-10-02, Apple M2 / 8 GB)

The initial scalar Belgium probe labelled 989 centres in 8.182 seconds, about
121 centres/second. Repeating the earlier builder's 40 million directly labelled
centres at that rate would take about 92 hours, so the world scalar approach was
rejected before launch. Vector polygon membership, reused local indexes and
bounded spherical coast queries replaced that hot path.

The completed Benelux + Canada pilot covers 1,753 resolution-3 blocks. Every one
of its 29,462,671 finest centres matched direct vector labelling and exactly one
stored ancestor for eligible centres (none for ineligible ocean). All 28,048
independent scalar spot checks agreed. The synthetic region additionally compares
every centre to the independent scalar oracle, including holes, overlaps,
nearest-city ties and offshore eligibility; separate seam/pole cases do the same.

Production directly labelled 8,906,318 centres in 648.125 summed worker seconds:
**13,742 centres/second**. Preparation, labelling and compaction totalled 792.817
worker seconds, or 0.4523 seconds/block, excluding verification and final Parquet
I/O. Charging all 41,162 world blocks this same average gives **2.59 hours with
two workers** before joins and quality checks. The 22,043 country-dependent
blocks alone extrapolate to 2.77 hours with one worker; most other blocks are
cheap ocean. This is a planning estimate, not a bound: geometry density, cache
warmup and shared CPU differ across countries. Raw timings and checks are in
`work/golden/pilot.json` and `work/golden/pilot-performance.json`.

The pilot's stored-cell quality checks pass for Paris and Eindhoven; 11 other
named fixtures await their world blocks. All 992 Benelux/Canadian settlement
observations have a country answer and agree with their source country. State
agreement is 990/992 and same-identity-or-containing-city agreement is 990/992.
The two Luxembourg state-code mismatches are inherited from reconciliation's
Esch Canton crosswalk. Canadian Brantford snaps from its source point to an r8
centre assigned to Eagle Place; Cole Harbour (PPLX) already returns ColeRidge
Estates at its original point. All four results match independent scalar lookup
at the r8 centre. Evidence is in `work/golden/pilot-disagreements.json`.

The pilot catalogue has no duplicate canonical IDs or dangling cell place IDs.
It retains 49 parent and sovereign references to `country:EH`, for which
reconciliation has no canonical country entity under its source perspective.
These are unresolved source catalogue references, explicitly counted in quality;
no replacement identity is invented. The partial spatial joins retain 983 source
country disagreements: postal 795, airports 10, trade 67 and IP 111. These counts
will change as the world build fills currently pending rows.


## Incremental v1 rebuild

`blocks.sqlite` caches the expensive actual H3 descendant envelopes independently
of the reconciliation builder. Changed country envelopes or offshore policy
recompute dependency intersections; unchanged normal roots reuse their stored
bounds. A legacy `blocks-<hash>.sqlite` supplies bounds after a SQLite integrity
check, with every dependency rechecked and seam roots enumerated again. The
cell implementation fingerprint includes the cell Arrow schema separately from
the place schema. Changing static links, reports or place-only columns does not
invalidate cells. Cell fingerprints still include each required country's verified
partition, land, runtime policy and spatial implementation. Unchanged source
rows and timezone hardlinks remain reusable.

Before replacing golden files, the controller publishes `completed: false`.
Completion requires both `work/golden/run.json` and `golden/manifest.json` to say
`completed: true`, with the integrity checks above passing. See the gated world
controller and exact launch/resume commands in [GOLDEN_V1.md](GOLDEN_V1.md).

# Thereabouts dataset 2026.10

Thereabouts is an offline geocoding database: it relates locations on land and the retained near-shore band to a country, subdivision and canonical city, and preserves place names and observations such as postal codes, airports, telephone prefixes, IP ranges and timezones. The files are ordinary Parquet tables; they can be queried directly without installing the Thereabouts client.

This release is an immutable, measured export of completed normalization outputs. Geographic decisions and original observations are retained. This subset contains country catalogues for MY, SG and spatial coverage in H3 blocks 836505fffffffff, 836500fffffffff, 836526fffffffff. Located observations are filtered to these blocks; unlocated observations for selected countries are retained. It is intended for search, exploration and offline applications; source coverage and city conventions vary, and these labels do not determine legal boundaries. Binary client packs are distributed separately and are not part of this directory.

## Directory layout

```text
dataset/2026.10/
├── airports/part.parquet  # 25 rows; 14,291 bytes
├── blocks/part.parquet  # not measured in this export
├── canonical_cities/country=*/part.parquet  # 408 rows; 34,789 bytes
├── cells/group=*/part.parquet  # 22,404 rows; 173,850 bytes
├── countries/part.parquet  # 2 rows; 18,584 bytes
├── ip_ranges/part.parquet  # 36,547 rows; 1,493,691 bytes
├── names/part.parquet  # not measured in this export
├── phone_metadata/part.parquet  # 2 rows; 26,146 bytes
├── phone_prefixes/part.parquet  # 0 rows; 2,063 bytes
├── place_to_city/country=*/part.parquet  # 28,063 rows; 417,842 bytes
├── places/country=*/part.parquet  # 28,063 rows; 3,919,626 bytes
├── plate_codes/part.parquet  # not measured in this export
├── plate_formats/part.parquet  # not measured in this export
├── plate_policy/part.parquet  # not measured in this export
├── plate_priors/part.parquet  # not measured in this export
├── postal_codes/part.parquet  # 64,317 rows; 1,161,474 bytes
├── subdivisions/part.parquet  # 37 rows; 10,370 bytes
├── timezone_cells/part.parquet  # 1,473 rows; 21,689 bytes
├── trade_locations/part.parquet  # 202 rows; 24,994 bytes
├── zone_tables/part.parquet  # 5 rows; 7,964 bytes
├── manifest.json  # file checksums, rows, schema, pins and policy
├── content.json  # partition-independent logical table digests
├── DATA_DICTIONARY.md  # tables, keys, relationships and coded values
├── data_dictionary.json  # the same dictionary, with the MCP tools, as JSON
├── DATA_LICENSES.md  # licences and attribution for contributing sources
├── DATASET_CARD.md  # purpose, coverage and measured statistics
├── CHANGES.md  # comparison with the previous logical digest
└── README.md  # this guide
```

The tree lists every logical entry; `*` denotes partitions. Paths in `manifest.json` are relative to this directory. Each table entry records its path, SHA256, compressed bytes and row count. Cell partitions group resolution-3 blocks by their resolution-1 parent (up to 49 blocks per group); this changes file packaging only. Country catalogues use `country=<code>` partitions. Other observations share one file per table. Empty tables retain a schema-bearing Parquet file. Partition labels route files; they are not stored columns. DuckDB and PyArrow detect `country=` and `group=` directories as Hive partitions and add `country` and `group` columns, so the examples below turn that off (`hive_partitioning=false` in DuckDB). `group` is a reserved SQL word: quote it as `"group"` if you keep the partition column.

## Cell keys and result semantics

Convert a WGS84 latitude/longitude to an H3 resolution-8 index. Its resolution-3 **parent** is the block; its resolution-1 parent selects the coalesced file. The directory `group=<r1 hex>` contains that parent's lowercase hexadecimal H3 index, without `0x` (for example, `group=81653ffffffffff`). Do not independently quantize the coordinate at a coarser resolution: H3 grids at different resolutions do not exactly nest geometrically. Stored cells are losslessly compacted: look for the resolution-8 index and then its ancestors down to resolution 3, choosing the finest match. No match means this subset has no result there, including outside its land coverage.

`h3` is lowercase hexadecimal text without `0x`; `h3_uint64` is the same unsigned 64-bit H3 index, with resolution in bits 52–55 and base-cell/child digits in the standard H3 representation. These are global H3 indexes, not a client pack's local integer offsets. `h3_resolution` says how many levels that stored row represents. Resolution 8 is the reference precision; coarser rows encode identical assignments for their descendant centres.

Each coalesced cells file contains **one Parquet row group per retained resolution-3 block**, ordered by ascending block ID. All rows of a block occupy that single row group, even when the input spans several files or batches. Blocks with no selected rows have no row group; an empty cells file has no row groups. Every cells row stores its block ID in the `block` column, which is therefore constant within a row group: a `block = '<r3 hex>'` filter lets DuckDB, PyArrow and other Parquet readers skip every other row group by its statistics. A filter on `h3_uint64` alone cannot, because H3 integers order by resolution before location and a row group holding several resolutions spans most of the key range. The `blocks` table lists every covered block with the cells file that holds it (`path`), its `row_group`, its `row_count` and the resolution-8 `reference_cells` its rows stand for. A covered block with `row_count` 0 stores no cells, and lookups there find no land; a block missing from `blocks` is outside this subset's coverage. `manifest.json` carries the same index: every cells entry in both `manifest.json.tables` and `manifest.json.files` includes `blocks: [{"block": "<r3 hex>", "row_group": 0, "rows": n}, ...]` and `empty_blocks: ["<r3 hex>", ...]`. Block IDs are lowercase hexadecimal without `0x`, `row_group` is the zero-based Parquet row-group index, and `rows` is that group's row count. Readers and the client pack writer locate the coordinate's resolution-3 parent in this index, read that row group, then match the stored ancestors described above. The file's `rows` equals the sum of its block counts; no row group contains multiple blocks.

Cell `country_id`, `state_id` and `city_id` link to `places.place_id`. The `canonical_cities` table contains eligible city/town anchors that can absorb other settlements; it is not a catalogue of every rural result. Standalone villages and other rural settlements can retain their own place IDs in `city_id`. `places.normalized_city_id` and `place_to_city.city_id` expose the reviewed mapping, including self-mappings and nulls for non-settlements. Source city/municipality strings are retained independently. The selected settlement can differ from the nearest named place or an administrative district. Legacy `city:` ID prefixes do not prove an entity is a city; inspect its `role` and `settlement_kind`.

IDs carry an entity namespace and its source identity: `country:MY` uses the country code, `state:overture:<uuid>` identifies a subdivision derived from Overture, and `city:geonames:<decimal id>` identifies a GeoNames-derived settlement. Other source namespaces and policy-defined IDs also occur; treat the complete string as opaque. IDs are deterministic for unchanged source identities and policy, but are **not guaranteed stable across monthly versions**. Source merges, removals, role changes and reviewed canonicalization can retire or redirect IDs. Store the release version with an ID, and compare `places` and `place_to_city` across versions before joining historical records; a matching name is not an identity guarantee.

Method columns explain the evidence or fallback used. `city_method = 'rural_nearest_distant'` is the distant-nearest flag: the policy's distant threshold is 25000 metres, and its nearest-city cutoff is 50000 metres. The full method set is `city_polygon`, `policy_polygon`, `urban_allocation`, `town_radius`, `rural_polygon`, `rural_nearest`, `rural_nearest_distant`, or null. Town radius is disabled in this snapshot; consult the exact policy in `manifest.json`. Null city means no qualifying assignment. An identifier lookup with `link_status = 'ambiguous'` preserves candidates in `place_ids`; `place_id` is populated only for a unique match. Spatial observations keep `cell_status` and nullable `country_disagrees`, so source disagreement is visible rather than silently corrected. Every place reference resolves to a `places` row: assembly refuses a dangling reference, as the client pack writer does.

Timezone membership is independent of eligible land. `timezone_cells` can store resolutions 0–8 and overlapping source memberships; query all ancestors down to resolution 0 for that table. In a spatial subset, a timezone row coarser than resolution 3 is retained whole when it overlaps a selected block, so its represented area can extend outside the subset.

## Quality gates

Before export, the pipeline checks every country's city boundaries and footprints. The measured export this page was rendered from predates these gates. A release's `manifest.json.quality_gates` records its blocking scope, its reviewed countries and its advisory totals.

## Tables and columns

Arrow types and physical nullability below are checked during assembly. “None” for units means an identifier, category, text or dimensionless value. Required logical keys are listed separately from Arrow nullability. Observation tables are keyed by `source` and `source_id`, one row per source record, so duplicate observations of one code or place are retained as separate rows. Assembly refuses a release that repeats any declared key. Counts and bytes are for this exact export, not a world estimate.

`places.place_id` is a required, non-null logical primary key. Its retained Arrow field is physically nullable, as are some other logical keys; assembly rejects null values in every declared logical primary-key column. “Yes in Arrow; no for the logical key” distinguishes these two contracts without changing the retained field schema.

### `airports`

Layout: `airports/part.parquet`. Primary key: source, source_id. 1 files, 25 rows, 14,291 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `source` | `string` | yes in Arrow; no for the logical key | none | Configured upstream source name |
| `source_id` | `string` | yes in Arrow; no for the logical key | none | Identifier of the original observation within its source |
| `ident` | `string` | yes | none | OurAirports airport identifier |
| `iata_code` | `string` | yes | none | IATA airport code, where available |
| `icao_code` | `string` | yes | none | ICAO airport code, where available |
| `gps_code` | `string` | yes | none | Source GPS airport code |
| `local_code` | `string` | yes | none | Local airport code |
| `type` | `string` | yes | none | Source-specific entity classification |
| `name` | `string` | yes | none | Preferred display name |
| `municipality` | `string` | yes | none | Source municipality text |
| `country_code` | `string` | yes | none | Source or reconciled ISO-like two-letter country code |
| `region_code` | `string` | yes | none | Source region or subdivision code |
| `latitude` | `double` | yes | degrees north | WGS84 latitude; positive north |
| `longitude` | `double` | yes | degrees east | WGS84 longitude; positive east |
| `h3` | `string` | yes | none | Lowercase hexadecimal H3 cell index, without 0x |
| `h3_uint64` | `uint64` | yes | none | Same H3 index as an unsigned 64-bit integer |
| `h3_resolution` | `uint8` | yes | H3 level | Resolution of this stored H3 index |
| `source_release` | `string` | yes | none | Pinned upstream release or inventory identifier |
| `license` | `string` | yes | none | Upstream licence identifier |
| `provenance` | `string` | yes | none | JSON source evidence and transformation provenance |
| `country_id` | `string` | yes | none | Reconciled country place identifier |
| `state_id` | `string` | yes | none | Reconciled first-level subdivision place identifier |
| `city_id` | `string` | yes | none | Selected settlement place ID, including standalone rural settlements; null if unassigned |
| `cell_country_code` | `string` | yes | none | Country code assigned by the geographic cell join |
| `cell_status` | `string` | yes | none | Cell join status: matched, unassigned, ineligible, pending or unlocated |
| `country_disagrees` | `bool` | yes | none | Whether source and cell country codes disagree; null if not comparable |

### `blocks`

Layout: `blocks/part.parquet`. Primary key: block. Not measured in this export.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `block` | `string` | no | none | Resolution 3 H3 block in lowercase hexadecimal without 0x; equals cells.block of every row it stores |
| `cell_group` | `string` | no | none | Resolution 1 H3 parent of the block in lowercase hexadecimal; the block's cells file sits in the directory cells/group=<cell_group>/ |
| `path` | `string` | no | none | The cells file that holds the block's rows, relative to the dataset directory; for a block without rows, the file whose manifest entry lists it as empty |
| `row_group` | `int64` | yes | none | Zero-based Parquet row group in path that holds every row of the block; null when the block stores no cells |
| `row_count` | `int64` | no | rows | Cells rows stored for the block; 0 when it stores none, and lookups there then answer that the location is not on land |
| `reference_cells` | `int64` | no | H3 resolution 8 cells | Resolution 8 cells that the block's stored rows stand for once compacted rows are expanded; at most 16,807 |

### `canonical_cities`

Layout: `canonical_cities/country=*/part.parquet`. Primary key: city_id. 2 files, 408 rows, 34,789 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `city_id` | `string` | no | none | Canonical city/town anchor ID |
| `place_id` | `string` | no | none | Reconciled place identifier |
| `country_code` | `string` | no | none | Source or reconciled ISO-like two-letter country code |
| `kind` | `string` | no | none | Canonical settlement kind |
| `name` | `string` | no | none | Preferred display name |
| `eligibility` | `string` | no | none | Evidence qualifying this place as a canonical city |
| `name_en` | `string` | yes | none | Preferred name only when its provenance explicitly identifies English |
| `latitude` | `double` | no | degrees north | WGS84 latitude; positive north |
| `longitude` | `double` | no | degrees east | WGS84 longitude; positive east |
| `population` | `int64` | yes | people | Source population estimate, not a current census assertion |
| `source_ids` | `string` | no | none | JSON list of contributing source identifiers |
| `footprint_references` | `string` | no | none | JSON references to source settlement footprints |
| `allocation_rule` | `string` | no | none | Rule used to allocate this canonical settlement |

### `cells`

Layout: `cells/group=*/part.parquet`. Primary key: h3_uint64. 1 files, 22,404 rows, 173,850 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `h3` | `string` | no | none | Lowercase hexadecimal H3 cell index, without 0x |
| `h3_uint64` | `uint64` | no | none | Same H3 index as an unsigned 64-bit integer |
| `h3_resolution` | `uint8` | no | H3 level | Resolution of this stored H3 index |
| `country_id` | `string` | yes | none | Reconciled country place identifier |
| `state_id` | `string` | yes | none | Reconciled first-level subdivision place identifier |
| `city_id` | `string` | yes | none | Selected settlement place ID, including standalone rural settlements; null if unassigned |
| `country_method` | `string` | yes | none | Country assignment evidence: area, or null when absent |
| `state_method` | `string` | yes | none | Subdivision assignment evidence: area, or null when absent |
| `city_method` | `string` | yes | none | Canonical city allocation rule, including distant-nearest classification |
| `land_method` | `string` | yes | none | Land eligibility evidence: land or offshore |
| `block` | `string` | no | none | Resolution 3 H3 parent of the cell (its block) in lowercase hexadecimal without 0x. Each Parquet row group holds one block, so filtering on block reads one row group |

### `countries`

Layout: `countries/part.parquet`. Primary key: country_code. 1 files, 2 rows, 18,584 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `source` | `string` | no | none | Configured upstream source name |
| `source_id` | `string` | no | none | Identifier of the original observation within its source |
| `country_code` | `string` | yes in Arrow; no for the logical key | none | Source or reconciled ISO-like two-letter country code |
| `alpha3` | `string` | yes | none | ISO alpha-3 country code |
| `numeric` | `string` | yes | none | ISO numeric country code represented as text |
| `name` | `string` | yes | none | Preferred display name |
| `calling_code` | `string` | yes | none | International telephone calling code, represented as text |
| `currency` | `string` | yes | none | Source currency code |
| `languages` | `string` | yes | none | Source language codes |
| `tld` | `string` | yes | none | Country internet top-level domain |
| `continent` | `string` | yes | none | Source continent identifier |
| `m49` | `string` | yes | none | UN M49 area code |
| `region_code` | `string` | yes | none | UN M49 code of the country's region, the continent level (for example 142 for Asia); airports.region_code is an ISO 3166-2 code instead |
| `region_name` | `string` | yes | none | UN region name |
| `subregion_code` | `string` | yes | none | UN subregion code |
| `subregion_name` | `string` | yes | none | UN subregion name |
| `intermediate_region_code` | `string` | yes | none | UN intermediate region code |
| `intermediate_region_name` | `string` | yes | none | UN intermediate region name |
| `source_release` | `string` | no | none | Pinned upstream release or inventory identifier |
| `license` | `string` | no | none | Upstream licence identifier |
| `provenance` | `string` | no | none | JSON source evidence and transformation provenance |
| `country_id` | `string` | yes | none | Reconciled country place identifier |
| `place_id` | `string` | yes | none | Uniquely matched reconciled place; null for ambiguous or unmatched observations |
| `link_status` | `string` | yes | none | Identifier link status: matched, ambiguous, unmatched or pending |
| `link_method` | `string` | yes | none | Rule used for the identifier link |
| `place_ids` | `list<element: string>` | yes | none | All candidate place identifiers; ambiguity is preserved |

### `ip_ranges`

Layout: `ip_ranges/part.parquet`. Primary key: source, source_id. 1 files, 36,547 rows, 1,493,691 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `source` | `string` | yes in Arrow; no for the logical key | none | Configured upstream source name |
| `source_id` | `string` | yes in Arrow; no for the logical key | none | Identifier of the original observation within its source |
| `ip_start` | `string` | yes | none | Inclusive first IP address as text |
| `ip_end` | `string` | yes | none | Inclusive last IP address as text |
| `country_code` | `string` | yes | none | Source or reconciled ISO-like two-letter country code |
| `region` | `string` | yes | none | Source region name |
| `city` | `string` | yes | none | Source city name; retained independently of the canonical city |
| `ip_version` | `uint8` | yes | address family | IP address family, 4 or 6 |
| `ip_start_packed` | `binary` | yes | none | Inclusive first address, 16-byte big-endian binary; IPv4 is left zero-padded |
| `ip_end_packed` | `binary` | yes | none | Inclusive last address, 16-byte big-endian binary; IPv4 is left zero-padded |
| `latitude` | `double` | yes | degrees north | WGS84 latitude; positive north |
| `longitude` | `double` | yes | degrees east | WGS84 longitude; positive east |
| `h3` | `string` | yes | none | Lowercase hexadecimal H3 cell index, without 0x |
| `h3_uint64` | `uint64` | yes | none | Same H3 index as an unsigned 64-bit integer |
| `h3_resolution` | `uint8` | yes | H3 level | Resolution of this stored H3 index |
| `source_release` | `string` | yes | none | Pinned upstream release or inventory identifier |
| `license` | `string` | yes | none | Upstream licence identifier |
| `provenance` | `string` | yes | none | JSON source evidence and transformation provenance |
| `country_id` | `string` | yes | none | Reconciled country place identifier |
| `state_id` | `string` | yes | none | Reconciled first-level subdivision place identifier |
| `city_id` | `string` | yes | none | Selected settlement place ID, including standalone rural settlements; null if unassigned |
| `cell_country_code` | `string` | yes | none | Country code assigned by the geographic cell join |
| `cell_status` | `string` | yes | none | Cell join status: matched, unassigned, ineligible, pending or unlocated |
| `country_disagrees` | `bool` | yes | none | Whether source and cell country codes disagree; null if not comparable |

### `names`

Layout: `names/part.parquet`. Primary key: city_id, name. Not measured in this export.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `city_id` | `string` | no | none | Canonical city/town anchor ID |
| `name` | `string` | no | none | The name as published by the source, NFC with collapsed whitespace |
| `kind` | `string` | no | none | How the name relates to the city: english, alternate or ascii |
| `language` | `string` | yes | none | Language tag from the source (GeoNames ISO 639 codes, Overture BCP 47 tags); null when the source gives none |
| `country_code` | `string` | no | none | Country code of the canonical city |
| `place_id` | `string` | no | none | Reconciled place whose source record carries the name |
| `source` | `string` | no | none | Configured upstream source name |
| `source_id` | `string` | no | none | The name's source row; a GeoNames alternate-name ID, a GeoNames feature ID for feature and ASCII names, or an Overture name digest |
| `source_release` | `string` | no | none | Pinned upstream release or inventory identifier |
| `license` | `string` | no | none | Upstream licence identifier |
| `provenance` | `string` | no | none | JSON source evidence and transformation provenance |

### `phone_metadata`

Layout: `phone_metadata/part.parquet`. Primary key: source, source_id. 1 files, 2 rows, 26,146 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `source` | `string` | no | none | Configured upstream source name |
| `source_id` | `string` | no | none | Identifier of the original observation within its source |
| `territory` | `string` | yes | none | Libphonenumber territory code |
| `calling_code` | `string` | yes | none | International telephone calling code, represented as text |
| `leading_digits` | `string` | yes | none | Libphonenumber leading-digit pattern |
| `national_prefix` | `string` | yes | none | National telephone prefix |
| `international_prefix` | `string` | yes | none | International dialling prefix pattern |
| `metadata_xml` | `string` | yes | none | Original territory metadata XML |
| `source_release` | `string` | no | none | Pinned upstream release or inventory identifier |
| `license` | `string` | no | none | Upstream licence identifier |
| `provenance` | `string` | no | none | JSON source evidence and transformation provenance |
| `country_id` | `string` | yes | none | Reconciled country place identifier |
| `place_id` | `string` | yes | none | Uniquely matched reconciled place; null for ambiguous or unmatched observations |
| `link_status` | `string` | yes | none | Identifier link status: matched, ambiguous, unmatched or pending |
| `link_method` | `string` | yes | none | Rule used for the identifier link |
| `place_ids` | `list<element: string>` | yes | none | All candidate place identifiers; ambiguity is preserved |

### `phone_prefixes`

Layout: `phone_prefixes/part.parquet`. Primary key: source, source_id. 1 files, 0 rows, 2,063 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `source` | `string` | no | none | Configured upstream source name |
| `source_id` | `string` | no | none | Identifier of the original observation within its source |
| `prefix` | `string` | yes | none | Telephone prefix as text; preserve leading zeros |
| `calling_code` | `string` | yes | none | International telephone calling code, represented as text |
| `language` | `string` | yes | none | Language of the prefix description |
| `description` | `string` | yes | none | Source geographic prefix description |
| `country_codes` | `list<element: string>` | no | none | Associated country codes; list of text codes |
| `source_release` | `string` | no | none | Pinned upstream release or inventory identifier |
| `license` | `string` | no | none | Upstream licence identifier |
| `provenance` | `string` | no | none | JSON source evidence and transformation provenance |
| `country_id` | `string` | yes | none | Reconciled country place identifier |
| `place_id` | `string` | yes | none | Uniquely matched reconciled place; null for ambiguous or unmatched observations |
| `link_status` | `string` | yes | none | Identifier link status: matched, ambiguous, unmatched or pending |
| `link_method` | `string` | yes | none | Rule used for the identifier link |
| `place_ids` | `list<element: string>` | yes | none | All candidate place identifiers; ambiguity is preserved |

### `place_to_city`

Layout: `place_to_city/country=*/part.parquet`. Primary key: place_id. 2 files, 28,063 rows, 417,842 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `place_id` | `string` | no | none | Reconciled place identifier |
| `city_id` | `string` | yes | none | Selected settlement place ID, including standalone rural settlements; null if unassigned |
| `method` | `string` | no | none | Mapping rule: self, spatial_absorption, policy_part, identity_alias or non_settlement |
| `evidence` | `string` | yes | none | JSON evidence supporting the allocation |

### `places`

Layout: `places/country=*/part.parquet`. Primary key: place_id. 2 files, 28,063 rows, 3,919,626 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `place_id` | `string` | yes in Arrow; no for the logical key | none | Reconciled place identifier |
| `name_en` | `string` | yes | none | Preferred name only when its provenance explicitly identifies English |
| `local_name` | `string` | yes | none | Source local/default name, without an inferred translation |
| `country_code` | `string` | yes | none | Source or reconciled ISO-like two-letter country code |
| `code` | `string` | yes | none | Published entity code |
| `code_status` | `string` | yes | none | Recorded source/code status, including user-assigned for XK; codes are not invented |
| `parent_id` | `string` | yes | none | Reconciled parent place identifier |
| `parent_method` | `string` | yes | none | Evidence used to select the parent |
| `sovereign_id` | `string` | yes | none | Sovereign country place identifier |
| `sovereign_code` | `string` | yes | none | Sovereign country code |
| `sovereign_name` | `string` | yes | none | Sovereign country display name |
| `population` | `int64` | yes | people | Source population estimate, not a current census assertion |
| `geonames_id` | `string` | yes | none | GeoNames identifier represented as text |
| `geonames_admin1` | `string` | yes | none | GeoNames first-level administrative code |
| `feature_code` | `string` | yes | none | GeoNames feature code |
| `source_subtype` | `string` | yes | none | Original source feature subtype |
| `settlement_class` | `string` | yes | none | Reconciled settlement classification |
| `city_exclusion` | `string` | yes | none | Reason this place is excluded from canonical city eligibility |
| `overture_ids` | `list<element: string>` | yes | none | Contributing Overture entity identifiers |
| `wikidata_ids` | `list<element: string>` | yes | none | Contributing Wikidata entity identifiers |
| `source_ids` | `string` | yes | none | JSON list of contributing source identifiers |
| `provenance` | `string` | yes | none | JSON source evidence and transformation provenance |
| `name_provenance` | `string` | yes | none | JSON evidence for the selected names |
| `link` | `string` | yes | none | JSON identity-link method and evidence, or JSON null |
| `name` | `string` | yes | none | Preferred display name |
| `role` | `string` | yes | none | Reconciled place role |
| `normalized_city_id` | `string` | yes | none | Selected settlement place ID; standalone rural settlements can map to themselves |
| `normalization_method` | `string` | yes | none | Rule used to select the normalized settlement identity |
| `settlement_kind` | `string` | yes | none | Canonical settlement classification |

### `plate_codes`

Layout: `plate_codes/part.parquet`. Primary key: none. Not measured in this export.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `country_code` | `string` | no | none | ISO-like two-letter code of the issuing country or territory |
| `code` | `string` | no | none | The code as the source spells it, with leading zeros and native script |
| `name_en` | `string` | yes | none | English label of the registration unit, as published |
| `name_local` | `string` | yes | none | Local-language label of the registration unit, as published |
| `unit_kind` | `string` | no | none | Source unit kind, such as district, state or registration_office; plate_policy maps it to a place or state level |
| `scope` | `string` | no | none | Whether the code identifies a registration unit or only associates an entity |
| `series_status` | `string` | no | none | Temporal status of the assertion |
| `series_id` | `string` | yes | none | Source series identifier the assertion belongs to |
| `subdivision_scope` | `string` | yes | none | Narrower context the assertion requires, such as a state series |
| `subdivision_codes` | `list<element: string>` | no | none | ISO 3166-2 identifiers the source gives for the unit; empty when none |
| `source` | `string` | no | none | Configured upstream source name |
| `source_url` | `string` | no | none | URL of the pinned document or query the assertion comes from |
| `license` | `string` | no | none | Licence identifier of that document |

### `plate_formats`

Layout: `plate_formats/part.parquet`. Primary key: none. Not measured in this export.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `country_code` | `string` | no | none | ISO-like two-letter code of the issuing country or territory |
| `series_id` | `string` | no | none | Source series identifier |
| `series_status` | `string` | no | none | Temporal status of the series as the format policy records it: current, or historic (a former series, which needs an explicit series to supply geography) |
| `pattern` | `string` | no | none | Full-match regular expression over the normalized plate text |
| `relaxed_pattern` | `string` | no | none | The pattern with separators optional or varied only at the positions the source shows |
| `code_group` | `string` | yes | none | Name of the capture group holding the registration code; null for series without one |
| `scripts` | `list<element: string>` | no | none | Script names the pattern uses, from plate_policy script_patterns |
| `fixed_national_marks` | `list<element: string>` | no | none | Literal national marks within the serial |
| `specificity_bits` | `double` | no | bits | Information heuristic of the pattern against a 36-character baseline; not a count of valid plates |
| `provenance` | `string` | no | none | JSON source fields of the pinned document: URL, licence, attribution, revision, digest and retrieval time |
| `source` | `string` | no | none | Configured upstream source name |
| `source_file` | `string` | no | none | Pinned file name of the source document |
| `source_url` | `string` | no | none | URL of the pinned source document |
| `license` | `string` | no | none | Licence identifier of that document |

### `plate_policy`

Layout: `plate_policy/part.parquet`. Primary key: none. Not measured in this export.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `policy_json` | `string` | no | none | The policy as one JSON object |

### `plate_priors`

Layout: `plate_priors/part.parquet`. Primary key: country_code. Not measured in this export.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `country_code` | `string` | no | none | ISO-like two-letter code of the counted country or territory |
| `vehicles` | `uint64` | no | vehicles | Published road motor vehicle count; definitions and dates differ between countries |
| `year` | `int64` | no | calendar year | Year of the published count |
| `source_label` | `string` | no | none | Country label as the source table prints it |
| `source` | `string` | no | none | Configured upstream source name |
| `source_url` | `string` | no | none | URL of the pinned source document |
| `license` | `string` | no | none | Licence identifier of that document |
| `provenance` | `string` | no | none | JSON source fields and the table row the count comes from |

### `postal_codes`

Layout: `postal_codes/part.parquet`. Primary key: source, source_id. 1 files, 64,317 rows, 1,161,474 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `source` | `string` | yes in Arrow; no for the logical key | none | Configured upstream source name |
| `source_id` | `string` | yes in Arrow; no for the logical key | none | Identifier of the original observation within its source |
| `country_code` | `string` | yes | none | Source or reconciled ISO-like two-letter country code |
| `postal_code` | `string` | yes | none | Postal code as text; preserve spaces and leading zeros |
| `place_name` | `string` | yes | none | Source postal place name |
| `admin1_name` | `string` | yes | none | Original level-1 administrative name |
| `admin1_code` | `string` | yes | none | Original level-1 administrative code |
| `admin2_name` | `string` | yes | none | Original level-2 administrative name |
| `admin2_code` | `string` | yes | none | Original level-2 administrative code |
| `admin3_name` | `string` | yes | none | Original level-3 administrative name |
| `admin3_code` | `string` | yes | none | Original level-3 administrative code |
| `accuracy` | `string` | yes | none | Original source positional-accuracy category, not metres |
| `variant` | `string` | yes | none | Original postal observation variant |
| `latitude` | `double` | yes | degrees north | WGS84 latitude; positive north |
| `longitude` | `double` | yes | degrees east | WGS84 longitude; positive east |
| `h3` | `string` | yes | none | Lowercase hexadecimal H3 cell index, without 0x |
| `h3_uint64` | `uint64` | yes | none | Same H3 index as an unsigned 64-bit integer |
| `h3_resolution` | `uint8` | yes | H3 level | Resolution of this stored H3 index |
| `source_release` | `string` | yes | none | Pinned upstream release or inventory identifier |
| `license` | `string` | yes | none | Upstream licence identifier |
| `provenance` | `string` | yes | none | JSON source evidence and transformation provenance |
| `country_id` | `string` | yes | none | Reconciled country place identifier |
| `state_id` | `string` | yes | none | Reconciled first-level subdivision place identifier |
| `city_id` | `string` | yes | none | Selected settlement place ID, including standalone rural settlements; null if unassigned |
| `cell_country_code` | `string` | yes | none | Country code assigned by the geographic cell join |
| `cell_status` | `string` | yes | none | Cell join status: matched, unassigned, ineligible, pending or unlocated |
| `country_disagrees` | `bool` | yes | none | Whether source and cell country codes disagree; null if not comparable |

### `subdivisions`

Layout: `subdivisions/part.parquet`. Primary key: code. 1 files, 37 rows, 10,370 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `source` | `string` | no | none | Configured upstream source name |
| `source_id` | `string` | no | none | Identifier of the original observation within its source |
| `code` | `string` | yes in Arrow; no for the logical key | none | Published entity code |
| `code_system` | `string` | yes | none | Namespace of the published administrative code |
| `country_code` | `string` | yes | none | Source or reconciled ISO-like two-letter country code |
| `name` | `string` | yes | none | Preferred display name |
| `type` | `string` | yes | none | Source-specific entity classification |
| `parent_code` | `string` | yes | none | Original source parent administrative code |
| `geoname_id` | `string` | yes | none | GeoNames identifier represented as text |
| `name_ascii` | `string` | yes | none | Source ASCII name |
| `source_release` | `string` | no | none | Pinned upstream release or inventory identifier |
| `license` | `string` | no | none | Upstream licence identifier |
| `provenance` | `string` | no | none | JSON source evidence and transformation provenance |
| `country_id` | `string` | yes | none | Reconciled country place identifier |
| `place_id` | `string` | yes | none | Uniquely matched reconciled place; null for ambiguous or unmatched observations |
| `link_status` | `string` | yes | none | Identifier link status: matched, ambiguous, unmatched or pending |
| `link_method` | `string` | yes | none | Rule used for the identifier link |
| `place_ids` | `list<element: string>` | yes | none | All candidate place identifiers; ambiguity is preserved |

### `timezone_cells`

Layout: `timezone_cells/part.parquet`. Primary key: source, source_id. 1 files, 1,473 rows, 21,689 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `source` | `string` | no | none | Configured upstream source name |
| `source_id` | `string` | no | none | Identifier of the original observation within its source |
| `tzid` | `string` | no | none | IANA timezone identifier |
| `h3` | `string` | no | none | Lowercase hexadecimal H3 cell index, without 0x |
| `h3_uint64` | `uint64` | no | none | Same H3 index as an unsigned 64-bit integer |
| `h3_resolution` | `uint8` | no | H3 level | Resolution of this stored H3 index |
| `source_release` | `string` | no | none | Pinned upstream release or inventory identifier |
| `license` | `string` | no | none | Upstream licence identifier |
| `provenance` | `string` | no | none | JSON source evidence and transformation provenance |

### `trade_locations`

Layout: `trade_locations/part.parquet`. Primary key: source, source_id. 1 files, 202 rows, 24,994 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `source` | `string` | yes in Arrow; no for the logical key | none | Configured upstream source name |
| `source_id` | `string` | yes in Arrow; no for the logical key | none | Identifier of the original observation within its source |
| `locode` | `string` | yes | none | UN/LOCODE identifier |
| `country_code` | `string` | yes | none | Source or reconciled ISO-like two-letter country code |
| `location` | `string` | yes | none | UN/LOCODE location component |
| `name` | `string` | yes | none | Preferred display name |
| `name_ascii` | `string` | yes | none | Source ASCII name |
| `subdivision_code` | `string` | yes | none | Source subdivision component |
| `function` | `string` | yes | none | UN/LOCODE function flags |
| `status` | `string` | yes | none | UN/LOCODE record status |
| `iata_code` | `string` | yes | none | IATA airport code, where available |
| `date` | `string` | yes | none | Original source record date string |
| `change` | `string` | yes | none | UN/LOCODE change marker |
| `remarks` | `string` | yes | none | Original source remarks |
| `coordinates_raw` | `string` | yes | none | Original source coordinate text |
| `latitude` | `double` | yes | degrees north | WGS84 latitude; positive north |
| `longitude` | `double` | yes | degrees east | WGS84 longitude; positive east |
| `h3` | `string` | yes | none | Lowercase hexadecimal H3 cell index, without 0x |
| `h3_uint64` | `uint64` | yes | none | Same H3 index as an unsigned 64-bit integer |
| `h3_resolution` | `uint8` | yes | H3 level | Resolution of this stored H3 index |
| `source_release` | `string` | yes | none | Pinned upstream release or inventory identifier |
| `license` | `string` | yes | none | Upstream licence identifier |
| `provenance` | `string` | yes | none | JSON source evidence and transformation provenance |
| `country_id` | `string` | yes | none | Reconciled country place identifier |
| `state_id` | `string` | yes | none | Reconciled first-level subdivision place identifier |
| `city_id` | `string` | yes | none | Selected settlement place ID, including standalone rural settlements; null if unassigned |
| `cell_country_code` | `string` | yes | none | Country code assigned by the geographic cell join |
| `cell_status` | `string` | yes | none | Cell join status: matched, unassigned, ineligible, pending or unlocated |
| `country_disagrees` | `bool` | yes | none | Whether source and cell country codes disagree; null if not comparable |

### `zone_tables`

Layout: `zone_tables/part.parquet`. Primary key: source, source_id. 1 files, 5 rows, 7,964 compressed bytes.

| Column | Arrow type | Nullable | Units | Meaning |
| --- | --- | --- | --- | --- |
| `source` | `string` | no | none | Configured upstream source name |
| `source_id` | `string` | no | none | Identifier of the original observation within its source |
| `table` | `string` | yes | none | Original timezone table name |
| `tzid` | `string` | yes | none | IANA timezone identifier |
| `country_codes` | `string` | yes | none | Associated country codes; comma-separated text |
| `comments` | `string` | yes | none | Original timezone comments |
| `coordinates_raw` | `string` | yes | none | Original source coordinate text |
| `latitude` | `double` | yes | degrees north | WGS84 latitude; positive north |
| `longitude` | `double` | yes | degrees east | WGS84 longitude; positive east |
| `h3` | `string` | yes | none | Lowercase hexadecimal H3 cell index, without 0x |
| `h3_uint64` | `uint64` | yes | none | Same H3 index as an unsigned 64-bit integer |
| `h3_resolution` | `uint8` | yes | H3 level | Resolution of this stored H3 index |
| `source_release` | `string` | no | none | Pinned upstream release or inventory identifier |
| `license` | `string` | no | none | Upstream licence identifier |
| `provenance` | `string` | no | none | JSON source evidence and transformation provenance |


## Worked coordinate reads

Install `duckdb`, `h3`, `pyarrow` and `pandas` in your analysis environment. Set `DATASET` to this directory. These three examples use 3.139, 101.6869, inside this subset, and print the matched cell's country, state, canonical city and method. All three query the same stored H3 ancestors and filter on the point's block first, so each reads one row group of one cells file.

### DuckDB SQL over local Parquet

```python
import os
from pathlib import Path
import duckdb
import h3

root = Path(os.environ["DATASET"])
cell = h3.latlng_to_cell(3.139, 101.6869, 8)
block = h3.cell_to_parent(cell, 3)
keys = [int(h3.cell_to_parent(cell, level), 16) for level in range(3, 9)]
pattern = str(root / "cells" / "**" / "*.parquet")
connection = duckdb.connect()
connection.execute("SET memory_limit='256MB'")
connection.execute("SET threads=1")
result = connection.execute(
    """WITH cell AS (
    SELECT country_id, state_id, city_id, city_method
    FROM read_parquet(?, hive_partitioning=false)
    WHERE block = ? AND h3_uint64 IN (SELECT unnest(?::UBIGINT[]))
    ORDER BY h3_resolution DESC LIMIT 1
  )
  SELECT c.country_id, c.state_id, c.city_id, p.name AS city_name, c.city_method
  FROM cell c LEFT JOIN read_parquet(?, hive_partitioning=false) p
    ON c.city_id = p.place_id""",
    [pattern, block, keys, str(root / "places" / "**" / "*.parquet")],
).fetchall()
assert len(result) == 1
assert result[0][3]  # A catalogue name for this example's selected settlement.
print(result)
connection.close()
```

A published copy is read the same way: replace the local directory in the first and fourth SQL parameters with the published `dataset/2026.10/` location. DuckDB needs its `httpfs` extension for remote paths. The name join uses `places`, which includes rural settlements; join `canonical_cities` separately for eligible city/town anchor details.

### PyArrow

```python
import os
from pathlib import Path
import h3
import pyarrow as pa
import pyarrow.dataset as ds

root = Path(os.environ["DATASET"])
cell = h3.latlng_to_cell(3.139, 101.6869, 8)
block = h3.cell_to_parent(cell, 3)
keys = pa.array(
    [int(h3.cell_to_parent(cell, level), 16) for level in range(3, 9)], type=pa.uint64()
)
table = ds.dataset(root / "cells", format="parquet").to_table(
    filter=(ds.field("block") == block) & ds.field("h3_uint64").isin(keys),
    columns=["country_id", "state_id", "city_id", "city_method", "h3_resolution"],
)
rows = sorted(table.to_pylist(), key=lambda row: row["h3_resolution"], reverse=True)
assert rows
print(
    {key: rows[0][key] for key in ("country_id", "state_id", "city_id", "city_method")}
)
```

### pandas with Parquet filter pushdown

```python
import os
from pathlib import Path
import h3
import pandas as pd

root = Path(os.environ["DATASET"])
cell = h3.latlng_to_cell(3.139, 101.6869, 8)
block = h3.cell_to_parent(cell, 3)
keys = [int(h3.cell_to_parent(cell, level), 16) for level in range(3, 9)]
frame = pd.read_parquet(
    root / "cells",
    engine="pyarrow",
    filters=[("block", "==", block), ("h3_uint64", "in", keys)],
    columns=["country_id", "state_id", "city_id", "city_method", "h3_resolution"],
)
frame = frame.sort_values("h3_resolution", ascending=False)
assert not frame.empty
print(frame.iloc[0][["country_id", "state_id", "city_id", "city_method"]].to_dict())
```

## Versions and integrity

Versions use `YYYY.MM[.patch]`: the monthly release and, when required, a positive patch number. A published version is immutable. `CHANGES.md` compares each table's logical digest and row count with the previous version. `content.json` hashes logical values and duplicate counts independently of partitioning, row order, Parquet metadata and compression. It covers every table except `blocks`, which indexes the packaging of `cells`. A packaging change can change file SHA256 without changing the logical digest.

Before using a downloaded release, verify every `manifest.json.files` entry by its byte size and SHA256; every Parquet entry also has its row count. The manifest itself is committed by the publication's `dataset/2026.10/_SUCCESS` receipt (the same receipt is written to `packs/2026.10/_SUCCESS`), written only after every dataset and requested pack object verifies. A directory without that remote receipt may be an incomplete upload. Locally assembled datasets are complete when their verified `manifest.json` is present. SHA256 detects corruption; it is not an authenticity signature.

The manifest's top-level keys are `schema_version`, `completed`, `data_root`, `version`, `inputs_hash`, `reference_resolution`, `block_resolution`, `normalization`, `sources`, `statistics`, `schemas`, `selection`, `input_manifest_sha256`, `logical_sha256`, `quality_gates`, `tables` and `files`. `tables` is the Parquet inventory; `files` also covers the generated documents and logical digest. File entries contain `path`, `size` (bytes) and `sha256`; table entries add `kind` and `rows`, and cells entries add the `blocks` row-group index and `empty_blocks` defined above. `sources` ships the exact pins and their per-file licence metadata. `schemas` describes columns and logical keys; `normalization` records the applied policy; `selection` declares subset countries and blocks; `quality_gates` summarizes the quality gates above.

With Python 3.11 or newer and `DATASET` set, verify local bytes without loading the tables:

```sh
python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["DATASET"]).resolve()
manifest = json.loads((root / "manifest.json").read_text())
for entry in manifest["files"]:
    path = (root / entry["path"]).resolve()
    assert path.is_relative_to(root), entry["path"]
    assert path.stat().st_size == entry["size"], entry["path"]
    with path.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == entry["sha256"], entry["path"]
print(f"Verified {len(manifest['files'])} files")
PY
```

## Next major schema

This release only adds to the schema: `cells.block`, the `blocks` table and declared keys. The next major schema version is planned to change the following, which will break queries that rely on the current shape.

- **One H3 key per table.** Tables keep a single H3 key column: the hexadecimal `h3` text or a signed `int64`, never both and never unsigned. Athena, BigQuery, Spark and pandas with nulls cannot hold unsigned 64-bit keys. Prefer `h3` and `block` in new queries.
- **Provenance split.** The per-row `provenance` JSON leaves the main tables. Source-level facts move to a `sources` table, and row-specific evidence to `<table>_evidence` tables keyed by `source` and `source_id`.
- **`group=` directories renamed.** Cells folders stop using the reserved word `group` as their partition label, or give way to files sorted by `block`. Reach a block's rows through the `block` column or the `blocks` table, not directory names.

## Licences, contact and citation

| Source | Licence | Attribution |
| --- | --- | --- |
| airports | Public-Domain | OurAirports contributors |
| codes | CC-BY-4.0 | GeoNames |
| codes | PDDL-1.0 | DataHub maintainers |
| codes | PDDL-1.0 | DataHub; UN Statistics Division; GeoNames; CLDR |
| dbip | CC-BY-4.0 | IP Geolocation by DB-IP https://db-ip.com |
| geoboundaries | CC0 1.0 Universal (CC0 1.0) Public Domain Dedication | geoBoundaries; Geoboundaries, Wikimedia |
| geoboundaries | CC0 1.0 Universal (CC0 1.0) Public Domain Dedication | geoBoundaries; National Georegister |
| geoboundaries | CC0 1.0 Universal (CC0 1.0) Public Domain Dedication | geoBoundaries; Wikimedia Commons, Wikimedia Commons |
| geoboundaries | CC0 1.0 Universal (CC0 1.0) Public Domain Dedication | geoBoundaries; geoBoundaries, Wikimedia |
| geoboundaries | CC0 1.0 Universal (CC0 1.0) Public Domain Dedication | geoBoundaries; geoBoundaries, Wikimedia Commons |
| geoboundaries | CC0 1.0 Universal (CC0 1.0) Public Domain Dedication | geoBoundaries; geoBoundaries, Wikipedia |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; Eurostat- European Commission |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; GeoBoundaries, World Bank |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; Kartverket |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; Knippenberg, Erwin, & Moritz, Meyer. “The Hidden Potential of Mobile Phone Data Insights on COVID-19 in the Gambia.” Data Blog, The World Bank Data Catalog |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; Myanmar Analytics Project, geoBoundaries |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; Open Africa, Code for Ethiopia |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; Ordce Survey Ireland |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; Sentinel-2 10-Meter Land Use/LandCover |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; Sentinel-2 10m LandCover |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; The Rwanda Geo Portal |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; World Bank |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; geoBoundaries, Knippenberg, Erwin, & Moritz, Meyer. “The Hidden Potential of Mobile Phone Data Insights on COVID-19 in the Gambia.” The World Bank Data Catalog |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; geoBoundaries, Open Data Watch |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; geoBoundaries, World Bank |
| geoboundaries | Creative Commons Attribution 4.0 (CC BY 4.0) | geoBoundaries; openAfrica, geoBoundaries |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Australian Bureau of Statistics |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Caribbean GeoPortal, N/A |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Czech Office for Surveying |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; DNCT - Direction Nationale des Colelctivités Territorielles, DNP - Direction Nationale de la Population, United Nations Office for the Coordination of Humanitarian Affairs, Mali |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; DNCT - Direction Nationale des Collectivités Territoriales, United Nations Office for the Coordination of Humanitarian Affairs, Mali |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Direcion General de Estadica, Encuestas y Censos |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; EuroGeoGraphics, Regional IM Working Group - Europe |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; EuroGeographics and NTES (Nomenclature of Territorial Units for Statistics - Republic of Macedonia State Statistical Office), Regional IM Working Group - Europe |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; EuroGeographics, Regional IM Working Group - Europe |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Eurostat- European Commission |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; GRID3 |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Geoboundaries, Open Data Nepal |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Geoportal of Latvia |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Haiti GeoPortal |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Instituto de Geografico Nacional |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Lýsigagnagátt |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Ministry of Land, Infrastructure, Transport and Tourism National Land Numerical Information Download Site |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; NZ Stats |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Pacific Data Hub |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Sentinel-2 10-Meter Land Use/LandCover |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; World Bank |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; World Bank Group, OCHA Côte d’Ivoire |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; Zambia Data Hub |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; geoBoundaries, Qatar Open Data Portal |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; geoBoundaries, Web Vectors Map |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; geoBoundaries, Wikimedia |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; geoBoundaries, Wikimedia Commons |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; geoBoundaries, Wikipedia |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; raster 2 polygon from Sentinel-2 10m Land Cover where Image Year = 2022 / exclude gridcode = 1 (water) / dissolve |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; raster2polygon from Sentinel-2 10m Land Cover where Image Year = 2021 / exclude gridcode = 1 (water) / dissolve / erase adm0 overlap / processed by IMB |
| geoboundaries | Creative Commons Attribution 4.0 International (CC BY 4.0) | geoBoundaries; raster2polygon from Sentinel-2 10m Land Cover where Image Year = 2021 / exclude gridcode = 1 (water) / dissolve / processed by IMB |
| geoboundaries | Open Data Commons Open Database License 1.0 | geoBoundaries; DG Territory |
| geoboundaries | Open Data Commons Open Database License 1.0 | geoBoundaries; IPUMS DHS |
| geoboundaries | Open Data Commons Open Database License 1.0 | geoBoundaries; Open Africa, Code for Ethiopia |
| geoboundaries | Open Data Commons Open Database License 1.0 | geoBoundaries; Open Street Map, Wambacher (https//wambachers-osm.website/boundaries/) |
| geoboundaries | Open Data Commons Open Database License 1.0 | geoBoundaries; OpenStreetMap, Wambacher |
| geoboundaries | Open Data Commons Open Database License 1.0 | geoBoundaries; OpenStreetMap, Wambachers |
| geoboundaries | Open Data Commons Open Database License 1.0 | geoBoundaries; Urban Redevelopment Authority, derived from ADM 3 |
| geoboundaries | Open Data Commons Open Database License 1.0 | geoBoundaries; geoBoundaries, OpenStreetMap |
| geoboundaries | Public Domain | geoBoundaries; GeoBolivia, Derived from ADM3 layer |
| geoboundaries | Public Domain | geoBoundaries; Natural Earth |
| geoboundaries | Public Domain | geoBoundaries; Natural Earth, geoBoundaries |
| geoboundaries | Public Domain | geoBoundaries; RCMRD GeoPortal, Africa GeoPortal |
| geoboundaries | Public Domain | geoBoundaries; RCMRD GeoPortal, geoBoundaries |
| geoboundaries | Public Domain | geoBoundaries; Stanford Digital Repository |
| geoboundaries | Public Domain | geoBoundaries; The World Factbook - CIA |
| geoboundaries | Public Domain | geoBoundaries; U.S. Census Bureau |
| geoboundaries | Public Domain | geoBoundaries; United States Census Bureau, MAF/TIGER Database |
| geoboundaries | Public Domain | geoBoundaries; Wikimedia Commons |
| geoboundaries | Public Domain | geoBoundaries; Wikimedia, geoBoundaries |
| geoboundaries | Public Domain | geoBoundaries; geoBoundaries, ArcGIS Hub |
| geoboundaries | Public Domain | geoBoundaries; geoBoundaries, FreeMapViewer |
| geoboundaries | Public Domain | geoBoundaries; geoBoundaries, RCMRD |
| geoboundaries | Public Domain | geoBoundaries; geoBoundaries, Wikimedia |
| geoboundaries | Public Domain | geoBoundaries; geoBoundaries, Wikimedia Commons |
| geoboundaries | Public Domain | geoBoundaries; geoBoundaries, Wikimedia Commons; credit to user 'Tachymetre' |
| geoboundaries | Public Domain | geoBoundaries; geoBoundaries, Wikipedia |
| geoboundaries | Public Domain | geoBoundaries; geoBoundaries, d-maps.com |
| geonames | CC-BY-4.0 | GeoNames |
| ghsl | CC-BY-4.0 | European Commission, Joint Research Centre (JRC), GHS-UCDB R2024A; Pesaresi et al. (2024), Advances on the Global Human Settlement Layer by joint assessment of Earth Observation and population survey data, International Journal of Digital Earth 17(1). https://doi.org/10.1080/17538947.2024.2390454 |
| osm_land | ODbL-1.0 | © OpenStreetMap contributors; coastline service osmdata.openstreetmap.de |
| overture | ODbL-1.0 | © OpenStreetMap contributors, Overture Maps Foundation |
| phone | Apache-2.0 | The Libphonenumber Authors; Google |
| postal | CC-BY-4.0 | GeoNames; GB contains Royal Mail copyright and database right 2022 |
| timezones | ODbL-1.0 | timezone-boundary-builder; OpenStreetMap contributors |
| timezones | Public-Domain | IANA Time Zone Database contributors |
| unlocode | PDDL-1.0 | UNECE; DataHub maintainers |

This derived database is licensed under ODbL 1.0, including its attribution and share-alike requirements for publicly used derivative databases. Preserve the source attribution in `DATA_LICENSES.md`; individual source terms still apply. The code's licence does not replace data licences. Pin identifiers, source checksums and provenance are in the manifest.

Contact: Ujjwal Rao (brightertiger), https://github.com/brightertiger/thereabouts/issues

Citation: Rao, U. (2026). Thereabouts offline geocoding dataset. https://github.com/brightertiger/thereabouts

Public documentation: https://github.com/brightertiger/thereabouts/blob/main/docs/dataset/README.md

# Thereabouts pack format 2

This is the normative specification of `thereabouts-pack-2`, version 2.0.
A pack is an immutable directory: `manifest.json`, inventoried binary shards,
and inventoried UTF-8 notices. All clients share the Rust implementation.
This document defines the `core` family. Name search and additional families
are reserved for later work; they are not implied by a core pack today.

## Identity and manifest

The manifest is a UTF-8 JSON object. Writers use compact JSON, sorted object
keys within arbitrary metadata objects, literal Unicode, and a final newline.
Struct field order is the order in the Rust definition; consumers must not
rely on JSON object order. The manifest SHA-256 is calculated over its exact
bytes and supplied externally by the installation pointer. It is not a field
inside itself. Adjacent checksums detect damage, not publisher authenticity.
JSON duplicate keys must not be emitted. Readers reject nonfinite numbers.
Unknown optional manifest fields may be ignored.

Required fields:

| Field | Meaning |
| --- | --- |
| `schema` | `thereabouts-pack-2` |
| `format_version`, `required_features` | Integers 2 and 0 |
| `family` | `core` |
| `data_version` | Nonempty immutable dataset release, such as `2026.10` |
| `reference_resolution`, `block_resolution` | Integers 8 and 3 |
| `input_digest` | Lowercase SHA-256 of the compact JSON `inputs` object |
| `inputs` | Writer identity, source manifest SHA-256 and export options |
| `sources` | Source/release/licence metadata supplied by the dataset publisher |
| `attribution` | Publisher-supplied attribution text; notices accompany it |
| `distant_over_m`, `cutoff_m` | Nonnegative uint32 nearest-policy bounds |
| `files` | Ordered artifact inventory |

`inputs` is `{manifest_sha256, options, writer}`. Writer identity is currently
`0.1.0`. Options contain `data_version`, `sources`, `attribution`, `notices`
(a name-to-text object), and `input_provenance`. A subset exporter records its
source inventory digest, every consumed original file digest, and selection
rules in `input_provenance`. No absolute build paths or run timestamps enter
pack identity. Different dataset versions must not be combined by a store.

An artifact has exactly the required fields `path`, `kind`, `size`, `sha256`.
Kinds are `cells`, `catalogue`, `metadata`, `notice`. Unknown kinds require a
new compatible reader. Paths are relative, slash-separated; empty components,
`.`/`..`, backslashes, colons, absolute paths and symlink components are invalid.
Paths are unique and cannot be `manifest.json`. Sizes are byte counts, hashes
are 64 lowercase hexadecimal characters. Only inventoried files are consumed.
Exactly one metadata artifact is required. Catalogue shards occur in global
ID order; spatial block IDs cannot occur in more than one shard. Empty packs
may have no spatial or catalogue shards. Notices have no binary header.

A reader rejects other format versions, nonzero required features, another
family, and resolutions other than 8/3 before interpreting records. Maximum
artifact size is 64 MiB; maximum manifest size is 16 MiB. A writer must split
catalogues before exceeding the artifact limit. The current writer emits one
resolution-3 block per cell shard and targets 4 MiB catalogue shards.

## Binary container

Unsigned integers are little endian, except the explicitly signed catalogue
coordinates. There is no native padding, compression or host-specific header.
Every shard starts with a 32-byte header:

| Offset | Type | Value |
| --- | --- | --- |
| 0 | 8 bytes | `54 48 45 52 45 50 4b 00` (`THEREPK` plus NUL) |
| 8, 10 | uint16 each | Major 2, minor 0 |
| 12 | uint32 | Required features: 0 |
| 16 | uint32 | Kind: 1 spatial, 2 catalogue, 3 metadata |
| 20 | uint32 | Section count: 4 spatial, 3 catalogue, 1 metadata |
| 24 | uint64 | Exact total file length |

Immediately following are 32-byte section descriptors, each
`type:u32, flags:u32, offset:u64, length:u64, count:u64`.
Section types are **local to the container**, consecutively numbered from 1.
Flags are zero. Each section starts at the next multiple of eight after the
previous section or directory. Padding is zero. Empty sections can share a
start. `length = count * width`. All spans must fit without overflow. There
are no overlaps, other gaps, or trailing bytes.

| Kind | Sections in order | Widths |
| --- | --- | --- |
| Spatial | blocks, sparse keys, values, label dictionary | 40, 2, 1, 20 |
| Catalogue | places, string offsets, UTF-8 text | 80, 8, 1 |
| Metadata | UTF-8 JSON object | 1 |

Kind 3 was exact codes in format 1. It means metadata only in format 2;
checking the version before the kind is mandatory.

## Spatial shards

A block is an H3 resolution-3 logical subtree. Its uint32 address is
`((base_cell * 7 + digit1) * 7 + digit2) * 7 + digit3`. Addresses lie in
0..41845, but pentagon holes are invalid: only 41,162 represent actual H3
cells. Directory records are sorted by this address.

Each 40-byte block record has:

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | uint32 | Block address |
| 4 | uint32 | Stored row count, at most 16,807 |
| 8 | uint64 | Byte offset into keys |
| 16 | uint32 | Encoding: 0 flat, 1 uint8 selectors, 2 uint16 selectors |
| 20 | uint32 | Dictionary count; zero for flat |
| 24 | uint64 | Byte offset into values |
| 32 | uint64 | Byte offset into dictionary |

For each of keys, values, dictionary, spans start at zero, are contiguous in
directory order and consume the section exactly. An empty block uses flat
encoding and consumes no rows. Empty blocks are meaningful coverage entries.

For a stored resolution `r` in 3..8, set `d = r - 3` and
`O(d) = (7**d - 1) / 6`. A sparse uint16 key is `O(d)` plus the base-7 integer
of H3 digits 4..r. Key 0 is the block root; maximum key is 19,607. Keys are
strictly increasing, encode valid H3 cells, and have no stored ancestor.

Labels contain five uint32 values, in this order:
`country_ref, state_ref, city_ref, flags, timezone_set_ref`.
Place references are pack-global; zero is null. The city is the final golden
canonical city or rural settlement, not a new runtime nearest selection.
Timezone-set references index `metadata.timezone_sets`, with 0 meaning null.

| Flag bits | Meaning |
| --- | --- |
| 0–2 | City method: 0 null, 1 `city_polygon`, 2 `policy_polygon`, 3 `urban_allocation`, 4 `town_radius`, 5 `rural_polygon`, 6 `rural_nearest`, 7 `rural_nearest_distant` |
| 3 | Country: 0 null, 1 `area` |
| 4 | State: 0 null, 1 `area` |
| 5 | Land: 0 land, 1 offshore |
| 6–31 | Reserved, zero |

Each country/state/city reference is nonzero if and only if its method is
nonzero. An all-zero geographic label is stored unassigned land, not an absent
row. Timezone coverage alone does not manufacture a country or city.

Flat values are `count * 20` bytes. A dictionary is unique labels sorted
lexicographically by all five **numeric** fields. Values are zero-based
selectors of the chosen width; every selector is below dictionary count.
Writers choose uint8 through 256 labels, uint16 above that, and use a dictionary
only when dictionary bytes plus selector bytes are less than flat bytes.
Ties choose flat. Every dictionary label is validated, even if unreferenced.

### Reverse and timezone semantics

Coordinates are finite degrees: latitude [-90,90], longitude [-180,180]. Convert
to an H3 resolution-8 cell once, then search its sparse key and logical parent
keys through key 0. Never independently reindex coordinates at coarser levels.
H3 indexing uses mode bit 59, base bits 45–51, resolution bits 52–55, and
three-bit digits at shifts `3*(15-level)`.

H3 queries accept canonical 15-character hexadecimal cells at resolutions 0..8.
A query at 3..8 searches only itself and stored ancestors, never an arbitrary
child. Resolutions 0..2 have no stored ancestor in this layout and return
`not_found`. Their representative point is the query cell centre; the public
`cell` field is the canonical query cell itself, retaining its resolution. Resolution >8 is `invalid_input`.

Absence of a block, absence of an ancestor, and stored unassigned land all
project to the new public `not_found` status. Opt-in evidence distinguishes
`outside_coverage`, `no_land`, `no_stored_ancestor`, and `unassigned`. In a subset,
`no_land` means no admitted stored land row, not a global ocean assertion.
Matches map methods 1–5 (and country/state-only context) to `contained`, 6 to
`nearest`, 7 to `nearest_distant`. Exact distance was not published by golden.
The flat `distance_band` is null except for nearest and nearest_distant.
For nearest it is `{greater_than_km: 0, at_most_km: distant_over_m / 1000}`;
for nearest_distant it is `{greater_than_km: distant_over_m / 1000,
at_most_km: cutoff_m / 1000}`. There is no `distance_km` field.
These bounds describe represented r8 centres, not distance from the input point
or from an inferred city centroid.

The writer joins all `timezone_cells` that contain each represented r8 centre.
It can split a spatial ancestor at timezone boundaries, then compact identical
five-field labels within each original stored source cell. Compaction must
not combine distinct source cells into a new coarse ancestor. Missing coverage produces set 0.
Overlapping zones form a sorted unique set, without choosing a source winner.
Timezone overlap never changes geographic status, including an all-zero
(unassigned) label. When a country is assigned, retain only zone names whose
`zone_tables.country_codes` comma-separated list contains that country code
(across any row for the zone). With no country, retain the whole set.
Exactly one survivor is returned as `timezone`; otherwise it is null and the
sorted surviving list is in `evidence.timezones` when evidence is requested.
Reverse never returns ambiguous or candidates. Forward ambiguity belongs to
later packages: flat fields null, ranked candidates, and no `selected` field.

## Catalogue shards

IDs start at 1 and concatenate catalogue shards in manifest order. Public place
IDs sort by unsigned UTF-8 bytes, are unique, and are never joined across packs
using their numeric references. The writer includes the transitive closure of
cell country/state/city references through the four relationships below.

An 80-byte record has twelve string references (uint32) at offsets 0..47:

```
place_id, name, name_en, local_name, role, settlement_kind,
country_code, code, code_status, parent_method, normalization_method, evidence
```

Offsets 48..63 hold four pack-global uint32 references:
`country_id, parent_id, sovereign_id, normalized_city_id`.
Offsets 64 and 68 hold signed i32 latitude and longitude in microdegrees.
Both are `-2147483648` for a missing point; otherwise latitude lies in
[-90000000,90000000], longitude in [-180000000,180000000]. Round source degrees
to nearest microdegree, halfway away from zero. Offset 72 is uint32 population,
with 0 meaning unknown. Offset 76 is a nullable **shard-local string reference**
to the unambiguous timezone of the catalogue anchor.

Canonical city rows supply preferred names, kind, centroid and population.
Other settlements have null points when the published place has no coordinate;
the reader never invents one. Place mappings must agree with normalized IDs.

Strings use a shard-local pool. Reference 0 is null. Offsets are uint64 starts
relative to text, plus one terminal offset. The first two offsets are zero;
a nonzero reference may designate an empty string. Offsets are nondecreasing,
the terminal equals text length, every span is valid UTF-8. Writers deduplicate
exact text in first-use order, including the added timezone string.
`place_id`, `name`, `role`, `settlement_kind`, `country_code`, `evidence` are
nonempty. Evidence is JSON text containing `golden_table`, decoded `source_ids`
and decoded `name_provenance`; it does not contain full raw provenance.

## Country, subdivision and zone tables

The metadata container's JSON object has four required arrays:

- `countries`: golden rows with nullable string fields `country_code`, `alpha3`,
  `numeric`, `name`, `calling_code`, `currency`, `languages`, `tld`, `continent`,
  `m49`, `region_code`, `region_name`, `subregion_code`, `subregion_name`,
  `intermediate_region_code`, `intermediate_region_name`.
- `subdivisions`: golden rows with nullable strings `code`, `code_system`,
  `country_code`, `name`, `type`, `parent_code`, `geoname_id`, `name_ascii`.
- `zone_tables`: golden IANA rows with nullable strings `table`, `tzid`,
  `country_codes`, `comments`, `coordinates_raw`, `h3`; nullable float degrees
  `latitude`, `longitude`; nullable integers `h3_uint64`, `h3_resolution`.
- `timezone_sets`: arrays of sorted unique nonempty IANA strings. Entry 0 is
  `[]`; subsequent entries contain one or more zones and receive references
  in first-use order. No implicit machine timezone database is consulted.

Golden rows additionally retain `source`, `source_id`, `source_release`,
`license`, and `provenance` (JSON encoded as a string). Joined country and
subdivision rows also retain nullable `country_id`, `place_id`, `link_status`,
`link_method`, and string-array `place_ids`. Unknown source metadata fields
are retained; consumers must not discard them when re-exporting a table.
Country and subdivision rows are indexed by country_code and code respectively;
duplicate codes or missing names are corrupt. State.code and State.name come
from the subdivision row matching the place code. Only when that row is absent
does the reader fall back to the place code and name. Country alpha3 is looked
up by country code. The provenance payload is retained once; the runtime indexes
refer to its rows. JSON side tables remain the wire representation.

A subset can omit metadata rows unrelated to its catalogue or timezone sets.
The current golden `zone_tables` holds zone.tab/zone1970.tab, not UTC transition
history; including it does not yet provide historical offset computation.

## Export, verification and resource limits

`write_pack(dataset_dir, "core", output_dir, options)` reads a completed
`golden-2` manifest and its declared Parquet inventory. `data_root` resolves
relative to that manifest. Core exports require cells, places, canonical_cities,
place_to_city, countries, subdivisions, timezone_cells and zone_tables in the
inventory. A deliberate fixture omission must be named explicitly in the
`allow_missing_tables` option. Both normalization policy bounds (`distant_m`,
`nearest_m`) are required nonnegative u32 integers, with distant <= nearest.
Population must be null (unknown) or a nonnegative u32 integer; invalid values
are rejected even on unused catalogue rows. Each consumed file is SHA-256 checked before and
after a bounded Arrow scan, with row counts checked. The writer does no
geographic reconciliation. Existing output is verified and returned only when
its input identity agrees; changed inputs are rejected without overwriting.

An exclusive `.<name>.building` directory owns SQLite and output artifacts.
Its parent defaults to the output parent; `options.staging_directory` selects
another parent on the same filesystem. This operational option is excluded
from pack identity. Preflight requires at least 5 GiB free plus an estimate of
eight times the consumed compressed input size and one maximum-size shard
(64 MiB). The estimate is admission policy, not a measured world-build bound.
No world export has been qualified. On success all shards are verified and the directory is renamed
atomically. Ordinary failures remove only the writer's own staging directory.
An interrupted process leaves staging for inspection; automatic resume is not
implemented. The caller must explicitly remove abandoned staging before retry.

The writer's admission budget constant is 512 MiB: 1,024-row Arrow batches,
Parquet row groups and Arrow batches at most 128 MiB uncompressed, a 16 MiB
SQLite cache, typed Arrow array reads (no batch JSON round trip), cached SQL
statements and multi-row inserts (at most 256 rows / 1 MiB, with a single
larger row bounded at 128 MiB) within the existing transaction,
block-local timezone joins, and bounded output shards. It rejects oversized
units. Full verification visits one decoded shard at a time. This budget is
not an allocator/RSS proof; world export remains unmeasured.

Runtime opening validates the manifest, inventory sizes, shard headers and
directories, and the small metadata table. Spatial payloads are decoded and
validated on first access (UTF-8, references, H3 validity, key ordering, ancestor
disjointness, dictionaries and method/null rules as applicable). Catalogue
shards retain raw records and string pools; individual places are constructed
on demand. Retained caches use byte-budgeted LRU eviction: 8 MiB for decoded
blocks, 16 MiB for raw catalogue bytes, and 4 MiB for on-demand decoded places. Active concurrent lookups can retain
evicted values until they finish. Files are reopened for cache misses; the pack
directory must remain available and immutable while a handle is open.

SHA-256 and whole-pack structural verification are opt-in at open
(`Pack::open(path, true)`, Python `Geocoder(path, verify=True)`).
`verify_pack` always checks every hash, every record and catalogue ordering
across shard boundaries. Default opening does not promise detection of damage
in unused payloads. Neither lookup nor verification performs network I/O. Missing store installations raise `data_not_installed` with message
`thereabouts data install core`. A missing explicit directory raises
`pack_not_found` and includes the path. Writer inputs raise
`writer_input_error` (Python `WriterInputError`, a `ValueError` subclass); staging
IO failures use `writer_error`. A stale stage names the directory to remove
before retry; failed cleanup never replaces the original export error. Unsupported
format/family raises `incompatible_data`, damage raises `corrupt_pack`, and
using a closed handle raises `closed_geocoder`. Ordinary misses and bad query
values are result statuses, not pack exceptions.


## Sample reproducibility

The sample builder requires an explicit `--golden` directory and writes only
inside its worktree. The manifest records the original golden manifest and
consumed file digests, subset definition, dataset label, Parquet writer settings
and PyArrow version. Byte-identical regeneration requires that recorded
PyArrow version; changed writer settings or versions produce a different input
identity instead of silently claiming identical bytes. Settings are Parquet 2.6,
Zstandard level 3, data pages 1.0, 65,536-row groups, dictionary encoding,
statistics and stored Arrow schema. The committed source extract is produced
from the same copied golden rows without calling the reverse engine.

## Columnar binding representation

The Python reverse_columns result omits candidates (reverse never produces
them) and evidence. Each string field is an int32 code array plus a
`<field>_categories` string array, in first-use order. Code -1 means null;
categories never contain null. String fields flatten nested names, such as
country_code, state_name, city_id and cell. Numeric point coordinates, city
point coordinates and distance_band_greater_than_km/distance_band_at_most_km
are float64 with a corresponding boolean `_valid` mask. city_population uses
uint32 and its own validity mask. Invalid slots contain NaN or zero but must
be interpreted through masks. Buffers are filled while iterating, without
retaining a batch of result objects.

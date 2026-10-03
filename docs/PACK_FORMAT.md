# Thereabouts pack format 2

This is the normative specification of `thereabouts-pack-2`, version 2.1 (forward) and the unchanged 2.0 core layouts.
A pack is an immutable directory: `manifest.json`, inventoried binary shards,
and inventoried UTF-8 notices. All clients share the Rust implementation.
This document defines `core` (reverse and canonical-city names), `postal`,
`airports`, `locode`, `phone`, `ip` and `plates`. Optional full-place names
remain a separate future family.

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
| `family` | `core`, `postal`, `airports`, `locode`, `phone`, `ip`, or `plates` |
| `data_version` | Nonempty immutable dataset release, such as `2026.10` |
| `reference_resolution`, `block_resolution` | Integers 8 and 3 |
| `input_digest` | Lowercase SHA-256 of the compact JSON `inputs` object |
| `inputs` | Writer identity, source manifest SHA-256 and export options |
| `sources` | Source/release/licence metadata supplied by the dataset publisher |
| `attribution` | Publisher-supplied attribution text; notices accompany it |
| `distant_over_m`, `cutoff_m` | Nonnegative uint32 nearest-policy bounds |
| `files` | Ordered artifact inventory |

`inputs` is `{manifest_sha256, options, writer}`. Writer identity is currently
`0.2.0` for core with names and `0.3.0` for forward families. Options contain `data_version`, `sources`, `attribution`, `notices`
(a name-to-text object), and `input_provenance`. A subset exporter records its
source inventory digest, every consumed original file digest, and selection
rules in `input_provenance`. No absolute build paths or run timestamps enter
pack identity. Different dataset versions must not be combined by a store.

An artifact has exactly the required fields `path`, `kind`, `size`, `sha256`.
Kinds are `cells`, `catalogue`, `metadata`, `notice`, `names`, `keys`,
and the compressed table roles defined below. Unknown kinds require a
new compatible reader. Paths are relative, slash-separated; empty components,
`.`/`..`, backslashes, colons, absolute paths and symlink components are invalid.
Paths are unique and cannot be `manifest.json`. Sizes are byte counts, hashes
are 64 lowercase hexadecimal characters. Only inventoried files are consumed.
Exactly one metadata artifact is required. Catalogue shards occur in global
ID order; spatial block IDs cannot occur in more than one shard. Empty packs
may have no spatial or catalogue shards. Notices have no binary header.

A reader rejects other format versions, nonzero required features, another
unsupported family, and resolutions other than 8/3 before interpreting records. Maximum
artifact size is 64 MiB; maximum manifest size is 16 MiB. A writer must split
catalogues before exceeding the artifact limit. The current writer emits one
resolution-3 block per cell shard and targets 4 MiB catalogue shards.

## Binary container

Unsigned integers are little endian, except the explicitly signed catalogue
coordinates. There is no native padding or host-specific header. Kinds 9 and 10 use
compressed payload blocks as specified below.
Every shard starts with a 32-byte header:

| Offset | Type | Value |
| --- | --- | --- |
| 0 | 8 bytes | `54 48 45 52 45 50 4b 00` (`THEREPK` plus NUL) |
| 8, 10 | uint16 each | Major 2; minor 1 for kinds 9–11, otherwise 0 |
| 12 | uint32 | Required features: 0 |
| 16 | uint32 | Kind: 1 spatial, 2 catalogue, 3 metadata, 4–7 retired forward layouts, 8 names, 9 integer table, 10 string pool, 11 key FST |
| 20 | uint32 | Section count, from the table below |
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
| Names | name FST, row offsets, spelling records, string offsets, UTF-8 text, trigram FST, posting offsets, postings | 1, 8, 20, 8, 1, 1, 8, 4 |

| Integer table / string pool | block directory, LZ4 block bytes | 48, 1 |
| Key FST | FST bytes | 1 |

Kinds 4–7 are obsolete format-2.0 forward artifacts and are not admitted by a
format-2.1 forward pack. Kind 3 was exact codes in format 1. It means metadata only in format 2;
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
If country narrowing leaves no survivors, retain the original zone set (including an otherwise valid single zone). Timezone overlap never changes geographic status, including an all-zero
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
`place_id`, `name`, `role`, `settlement_kind`, `country_code` are nonempty.
Core additionally supplies evidence. When present, evidence is JSON text containing `golden_table`, decoded `source_ids`
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

An exclusive .<name>.building directory owns output artifacts. SQLite defaults to that directory; options.sqlite_directory can place its temporary file on another filesystem, with its own disk admission check. Both paths are operational and excluded from pack identity.
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
SQLite cache, borrowed typed Arrow fields and typed SQLite columns (no per-row JSON maps in cells, places, canonical cities, mappings or timezone scans), cached SQL
statements and multi-row inserts (at most 256 rows / 999 bindings / 1 MiB, with a single
larger row bounded at 128 MiB) within the existing transaction,
block-local timezone joins, and bounded output shards. It rejects oversized
units. Full verification visits one decoded shard at a time. This budget is
not an allocator/RSS proof; world export remains unmeasured.

Runtime opening validates the manifest, inventory sizes, shard headers and
directories, and the small metadata table. Spatial payloads are decoded and
validated on first access (UTF-8, references, H3 validity, key ordering, ancestor
disjointness, dictionaries and method/null rules as applicable). Catalogue
records range-read their 80-byte record, referenced offset pairs and UTF-8
spans only. No catalogue miss loads or validates an entire shard. Retained
caches use constant-time linked-key LRU eviction: 8 MiB for decoded blocks and
4 MiB for decoded places. IO and decoding occur outside the cache mutex.
Concurrent misses may decode the same immutable record; insertion reuses an
existing cached value. Active readers can retain evicted values until finished.
Every shard retains the file handle opened with its validated directory and
uses positioned reads; replacing its path cannot change the handle's contents.
In-place mutation of an open shard is unsupported.

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

## Compressed forward tables (format 2.1)

Every forward family requires manifest `format_minor: 1`; older forward
packs are incompatible and must be rebuilt. Core spatial/name packs retain
minor zero. Shared catalogue and metadata containers keep their unchanged
minor-zero layouts; kinds 9, 10 and 11 require container minor one.

Integer-table artifacts (kind 9) and string-pool artifacts (kind 10) contain
two sections: a directory of 48-byte entries and compressed byte payloads.
Artifacts for the same role concatenate in manifest order. Row ordinals are
zero-based and continuous across these artifacts. An empty table is represented
by one artifact with two empty sections.

Each directory entry contains:

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | u64 | First global row ordinal |
| 8 | u32 | Row count, 1 through 4,096 |
| 12 | u32 | Uncompressed byte length, at most 65,536 |
| 16 | u64 | Byte offset relative to compressed-payload section |
| 24 | u32 | Compressed byte length, at most 65,536 |
| 28 | u32 | Reserved zero |
| 32, 40 | u64 each | Low and high words of the first search key |

Search keys are row ordinals except for IP starts/evidence, where they are
the first address in the block. Start-table keys are strictly increasing and
must agree with the first decoded start. Payload spans are consecutive from
zero and consume the section exactly. Blocks use raw LZ4 block encoding,
without a frame, checksum or prepended length; lengths come only from the
checked directory. The writer limits raw blocks to 65,024 bytes to allow LZ4
expansion and recursively halves oversized integer blocks. It targets 8 MiB
compressed shards. Neither compressed nor uncompressed blocks may exceed
64 KiB. Decoded integer vectors can occupy more memory than their packed form.

An uncompressed integer block starts with row count u32 and column count u32.
Column count is 1 through 64; every family fixes its schema below. Columns
follow consecutively, each with a 16-byte descriptor and variable payload:

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | u8 | Mode: 0 frame of reference; 1 local dictionary |
| 1 | u8 | Bits per packed value, 0 through 64 |
| 2 | u16 | Dictionary entries; zero in mode 0 |
| 4 | u32 | Reserved zero |
| 8 | u64 | Base value; zero in mode 1 |

Mode 0 stores minimum plus unsigned deltas, with the minimum in the base.
Mode 1 stores a strictly increasing dictionary of u64 values immediately after
the descriptor, then zero-based dictionary selectors. Dictionary cardinality
is 1 through row count. In either mode, packed values follow in row order:
value bit b for row r is bit `(r * width + b) % 8` in byte
`floor((r * width + b) / 8)`. Padding bits are zero. Width zero has no payload.
There is no per-column alignment. Addition cannot overflow and dictionary
selectors must exist. The block ends immediately after the final payload.
Writers choose the minimum width needed, and dictionary mode only when its
8-byte entries plus packed selectors are strictly smaller than packed deltas.
Byte widths 8/16/32/64 are the same representation as fixed-width integers.

A string-pool block is `row_count + 1` u32 offsets followed by UTF-8 bytes.
Offsets begin at zero, are nondecreasing, and the terminal offset equals the
text length; every span must be valid UTF-8. A pack has one logical pool,
partitioned as `strings` (query fields) and `evidence_strings` (cold fields).
Each partition reserves row zero as the empty null slot; positive rows may
represent an actual empty string. String reference zero is null. Otherwise
reference `2*r` selects row r in strings, and `2*r+1` selects row r in
evidence_strings. Dictionary tables use zero-based row ordinals, not these
tagged string references. Text interning is exact Unicode byte equality.

The non-plate families require `forward_columns` in the manifest, containing
`source_rows` (original input observations, one per airport) and the ordered
`detail_fields` listed below. These roles have fixed integer columns:

| Role | Columns in order |
| --- | --- |
| records | location ordinal |
| postings (airports only) | record ordinal |
| geographies | country, state, city catalogue references |
| locations | geography ordinal, latitude bits, longitude bits, evidence name string |
| evidence / evidence4 / evidence6 | source string, source-id prefix string, line-plus-one, code string, scheme string, details ordinal |
| details | One nullable JSON-scalar string reference per detail_fields entry |
| starts4 / starts6 (IP only) | address high 64 bits, address low 64 bits, location ordinal |

Geographies, locations and details reserve row zero as an all-zero null tuple.
Coordinates in locations store the u32 bit pattern of signed i32 microdegrees;
both must be i32::MIN when absent. Geography references use the shared catalogue.
Records point to locations; their one-based ordinal supplies stable identity
without fetching source strings. Source identity remains authoritative during
writing. Airports have exactly one record per (source, source_id); conflicting
geographic, coordinate, name or detail fields for that identity are rejected.

The evidence table aligns exactly with records, or with each IP start table.
A non-null source ID with a canonical decimal u32 suffix after its final colon
is stored as the prefix including colon and suffix + 1. Line zero means the
prefix contains the full source ID. A nonzero line reconstructs prefix plus
decimal(line - 1), without leading zeroes. Source and reconstructed source_id
must be nonempty. Details reconstruct an object from non-null scalar references;
a reference to the text `null` represents an explicit JSON null. The object
is not stored per row. Evidence-only names and source fields are never needed
to project a normal result.

Every non-IP, non-plate family has exactly one `keys` artifact: kind 11 with
one byte section containing the FST map encoding specified under “FST encoding”
below. Its keys are distinct unsigned-byte-sorted UTF-8 compound keys, and values
are first row ordinals. The next key's value is the exclusive end; the final end
is the records row count (postings row count for airports). A key owns at least
one row. First ordinal is zero and subsequent values strictly increase.
Airport postings map each scheme key to its record ordinals; repeated keys do
not duplicate airport records. The other families group records in key order,
then source, source_id and name byte order. Phone queries try prefixes from
longest to shortest and use only the first terminal found.

IP has separate starts4 and starts6 tables; addresses are unsigned numeric
values, with IPv4 confined to its low 32 bits. Starts increase strictly across
blocks and shards. A row ends immediately before the next start, or at the
address-family maximum for the last row. A location-zero row marks an uncovered
gap and has an all-zero evidence row. A final gap row follows the last covered
interval unless coverage ends at the family maximum. Addresses before the first
start are uncovered. The reader binary-searches block keys, decompresses one
block, and binary-searches its starts. No ends are stored per row.

Readers retain file handles and directories. Each compressed table has an
8 MiB decoded-block LRU; IO and decoding occur outside its lock. Evidence
directories are admitted at open but evidence payloads are fetched only for
evidence=True or explicit full verification. Full verification checks every
block, every reference, every key span and every source record. The shared
forward catalogue omits local_name, code_status, parent_method,
normalization_method and evidence strings; their record slots are null.
Forward metadata keeps country_code/alpha3/name and subdivision
code/country_code/name for referenced rows, without provenance or timezone
tables. Plates retains all countries because each is a valid explicit hint.

## Postal family

A postal manifest has family **postal**, zero distance-policy bounds, and
normalization **["strip_ascii", "upper_ascii", "remove_ascii_spaces"]**.
Operations execute in that order: trim ASCII whitespace at the ends, uppercase
ASCII a–z, then remove U+0020 throughout. Do not remove hyphens or infer numbers.
The same operations are applied during export and lookup. Unknown operations or
a different postal rule sequence are incompatible data. The key is the uppercase
two-letter source country, one NUL byte, then normalized postal code. Source
country and the country assigned by the dataset may differ; neither is rewritten.

Each postal pack contains metadata, any referenced catalogue shards, at least
one **keys** FST and the required compressed tables, and notices. Catalogue references are local to this pack,
with the same records and global ordering as core. Empty indexes are explicit.
The exporter requires postal_codes, places, canonical_cities,
place_to_city, countries, and subdivisions; fixture exceptions must be
explicit. Catalogue closure includes every assigned country, state and city and
their published relationships. An available place-to-city mapping replaces the
source city's reference. No nearest city or missing coordinate is invented.

Postal details have columns admin1_name, admin1_code, admin2_name, admin2_code,
admin3_name, admin3_code, accuracy and variant, in that order. Evidence retains
the source place name. The public point is the source point, separately from
city.point; missing coordinates are never inferred.

postal(code, country=...) returns kind: postal, match: exact for matches.
Missing/invalid country, empty/NUL code, and non-string input return
invalid_input with an actionable hint; this optional field is omitted when
absent. No country is inferred. Duplicate observations for the same canonical
city and country/state context form one answer. Unmapped observations retain
source identity instead. A grouped answer uses the first source point ordered
by source, source_id, then name. Several distinct answers produce ambiguous,
null flat fields and candidates ranked by population, with stable identity ties.
rank_basis is population. Missing populations rank as zero, without claiming
a population value. Misses have not_found.

Forward column batches include candidate_offsets (u64, N+1 entries, starting
at 0), plus the usual columns with a candidate_ prefix for the concatenated
matched candidates. Offsets slice candidate rows for each input. Dictionary
categories and validity masks follow the reverse convention; hint is a nullable
dictionary string column. Scalar and batch calls use the same core lookup.

## Airports family

The airports family requires the same catalogue and metadata tables as postal.
Its primary input is the dataset table airports. Every non-null published
iata_code, icao_code, gps_code, local_code and ident is indexed under the respective
scheme iata, icao, gps, local and ident. No scheme is inferred from another field.
Normalization is exactly ["strip_ascii", "upper_ascii"], in that order.

The shared columnar tables and FST index are used. Keys
are UTF-8 scheme + NUL + country + NUL + normalized code. Country is the
uppercase two-letter source country. All schemes except local additionally
have a global key with the empty country component. The observation name
is the airport name, code and scheme describe the indexed code, and details
columns are type, municipality and region_code (nullable strings), in that order.

An explicit scheme searches only that namespace. Omitted scheme searches IATA
then ICAO and combines all results. Multiple records with the same source and
source_id form one airport; different identities produce ranked ambiguous
candidates, with flat fields null. Local requires an explicit country; unknown
schemes and malformed countries are invalid_input with a hint. Published null
geography remains null, even when a source country code can scope its index.
Point is the published airport point. Canonical geography follows place_to_city.
Match is exact and kind is airport. Evidence retains the contributing names,
schemes and source identities. Airport columns use the postal column contract.

## LOCODE family

The locode family consumes trade_locations and the same required geographic
tables as postal. Its normalization is ["strip_ascii", "upper_ascii"]. It uses
the key FST with a full normalized LOCODE as the key, without a
separator. LOCODE has two ASCII uppercase country letters and three uppercase
ASCII letters or digits. Export rejects disagreement between locode,
country_code and location. Lookup accepts the full code or three characters
plus country. Conflicting or malformed country hints are invalid_input.

Evidence reconstructs name, the full key as code and scheme "unlocode".
Details columns, in order, are name_ascii, subdivision_code, function, status,
iata_code, date, change, remarks and coordinates_raw. Point and geographic
references are published associations with canonical-city rollup, not a new
reverse lookup. Identity is source plus source_id. Kind is trade_location and
match is exact. Duplicate identities merge evidence; multiple identities are
ambiguous. Column output has the shared dictionary and candidate-offset layout.

## Phone family

The phone family requires phone_prefixes, phone_metadata and the five geographic
tables required by postal. The manifest normalization is exactly
["e164_plus", "strip_phone_presentation"]. Input must have a leading plus;
ASCII spaces, hyphens and parentheses after it are ignored. The remaining 1–15
ASCII digits must begin with 1–9. National numbers, extensions and Unicode
digits are invalid_input. This is prefix lookup, not subscriber validation.

The FST maps digit prefixes to compressed record spans. Query truncation is
bounded by the E.164 maximum of 15 digits; only the longest existing prefix
contributes. Empty input emits an explicit empty FST and record/evidence tables.

Each phone_prefixes row is indexed at prefix. Each phone_metadata territory is
a fallback at calling_code. Territory 001 is explicitly non-geographic and is
excluded. Other country references must exist; an unlinked territory cannot
silently acquire a guessed country. The source place_ids/place_id links determine
state and canonical city; description is never parsed into geography. Each
distinct linked country/state/city is a candidate; translations and metadata
observations for the same geography merge into evidence. Kind is phone_prefix,
match exact, source point null, and country is present on each matched candidate.
Multiple countries at a shared calling code are ambiguous. Observation name is
description, code is the digit prefix, scheme is prefix or calling_code; details
retains language, description, calling_code, leading_digits, national_prefix,
international_prefix, link_status and link_method when present. The metadata
regex fields are provenance, not a second number parser.

## IP family

The ip family requires ip_ranges and the same geographic tables as postal.
Normalization is ["ip_literal"]. Input is a trimmed IPv4 or IPv6 address literal.
Ports, CIDR suffixes, IPv6 zones and noncanonical IPv4 leading zeroes are invalid.
IPv4-mapped IPv6 literals remain IPv6; the two address families never alias.

The starts4/starts6 compressed tables use implicit ends and null-location
gap rows as defined above. Empty families emit explicit empty tables, including
aligned evidence4/evidence6. Details columns are city, country_code, region,
in that order, including explicit nulls.

The writer requires packed endpoints to agree with the published textual
addresses and ip_version. It rejects overlaps instead of choosing an arbitrary
source. Kind is ip_range, match exact. Source point and canonical geographic
associations are projected. Observation name is the published city text, code
is start + U+2013 + end, scheme is ipv4 or ipv6, and details JSON preserves
country_code, region and city text, including explicit nulls. Source text remains
available in evidence when it differs from canonical country/state/city fields.

## Plates family

The plates family currently takes an explicit adapter dataset with table kinds
plate_formats, plate_codes, plate_policy, plate_priors, and the five geographic
tables required by postal. The adapter reads the plate-country release's bundle
and inventoried Parquet artifacts. When the pipeline supplies its plates dataset
table, the adapter input switches to that table; the wire model is unchanged.
Missing vehicle priors are allowed only by the explicit fixture option
allow_missing_tables=["plate_priors"], and are recorded in the wire payload.

The manifest's plate_columns object contains policy, prior_available and
source_rows (formats plus codes). Policy has max_input_length (64),
code_separators (string), levels (unit-kind to place/state map), script_patterns
(script-to-regex map), weights (finite known_code, fixed_mark, script,
specificity, log_vehicle_prior, relaxed_penalty), geography, decimal_zeroes
(code points beginning ten decimal digits), and decimal_unicode_version.
Geography has excluded_countries and allowed_scopes (string arrays),
state_prefix (country to length map), unknown_status_eligible,
block_if_non_geographic_format_matches and historic_requires_explicit_series
(booleans). prior_available must equal whether plate_priors has any rows.

All plate data uses kinds 9 and 10, with these fixed integer schemas:

| Role | Columns in order |
| --- | --- |
| plate_formats | country_code, series_id, series_status, pattern, relaxed_pattern, code_group, scripts, fixed_national_marks, specificity_bits |
| plate_codes | country_code, code, name_en, name_local, unit_kind, scope, series_status, subdivision_scope, subdivision_codes, source_url identity |
| plate_priors | country_code, vehicles |
| plate_format_evidence | provenance |
| plate_code_evidence | source_url, license |

Every field is a pooled string reference except specificity_bits (the u64
IEEE-754 bit pattern of a finite f64) and vehicles (u64). scripts,
fixed_national_marks and subdivision_codes are pooled JSON string arrays.
Query string fields must reference the hot pool; source_url identity is a cold
pool reference compared numerically for deduplication without reading its text.
Each cold table aligns with its source table. provenance is pooled JSON text;
URLs and licences are pooled plain text. Every role is inventoried even if empty.
Formats and codes preserve input order. Invalid regexes or missing named
captures fail admission. Null is permitted only for code_group, name_en,
name_local and subdivision_scope; empty strings remain distinct from null.

Normalization is exactly ["nfc", "upper_ascii", "collapse_python_whitespace"].
NFC precedes ASCII-only uppercase. Whitespace is U+0009–000D, U+001C–001F,
U+0020, U+0085, U+00A0, U+1680, U+2000–200A, U+2028–2029, U+202F, U+205F,
U+3000. Runs become one ASCII space and are trimmed. No script transliteration
or confusable folding occurs. More than 64 Unicode scalar values disables
format inference. Captured-code equality additionally removes code_separators
and maps the declared decimal ranges to ASCII, preserving leading zeroes.

Matching, ranking and geographic eligibility follow docs/PLATES.md's
"Deterministic reference contract" and "Geographic eligibility and reasons":
try exact before relaxed per rule; country score is the maximum rule score;
deduplicate (country, temporal status, used pattern, capture) in source order.
Score is the weighted sum of known-code presence, fixed-mark presence, maximum
observed non-Latin script rarity, exported specificity, log2 vehicle count and
negative relaxed penalty. Rarity is log2(country-table count / max(1, countries
whose format metadata contains the script)). Missing country priors use the
median of supplied counts; an explicitly absent prior table disables that term.
Round to six decimals, ties to even; sort descending score then ISO code.
Matching-rule evidence sorts by score then series ID, preserving source-order ties.

Only allowed registration-unit scopes and compatible temporal status supply
geography; unknown status and narrower subdivision prerequisites are excluded
under the policy. Historic geography requires explicit series. Non-geographic
series may block geography; configured countries may require unsupported state
context. State-prefix fallback uses only declared prefix lengths and source rows.
All distinct eligible assertions remain in evidence; conflicting state names
leave flat state null. When a unique state assertion has one explicit subdivision
row, state fields come from that row; otherwise the published code/name is used.
Registration offices and source entity associations never become canonical cities.

A known country hint always returns that country with kind plate and match exact,
even for empty input or unknown formats. Invalid country identifiers return
invalid_input. Without a hint, inferred countries are ranked candidates with
status ambiguous and flat fields null, including singleton candidates: this
open-world catalogue does not certify country uniqueness. No matches return
not_found. rank_basis is plate_evidence, or
plate_evidence_without_vehicle_prior for an explicitly incomplete fixture.
Source series, score, capture and geographic assertions are opt-in evidence.

## Canonical-city names in core (kind 8)

Core exports include every canonical_cities row and its geographic ancestry.
The primary name and non-null name_en feed the same index. An optional names
table contributes city_id, name, kind; kind is primary, english, alternate or
ascii. References must identify a canonical city. This adapter is tested with
synthetic alternates pending publication of the real names table. Names are
part of core, not a separate installable geocode family. A historical core pack
without names remains usable for reverse; geocode reports incompatible_data.

The manifest's name_normalization object is mandatory exactly when names
artifacts exist. Its fields are steps (ordered string array), casefold_unicode,
normalization_unicode (strings), and expansions (string-to-string object).
Supported steps, in order, are nfkc, casefold_full_non_turkic,
fold_latin_cyrillic_greek, collapse_punctuation_whitespace, expand_tokens.
The Unicode casefold table is 9.0.0, and decomposition/composition is 17.0.0.
Readers reject unsupported steps or table versions rather than substituting
their host's Unicode version. Current expansions are st → saint, ste → sainte;
keys and values must be nonempty lowercase ASCII words.

Normalize as follows: NFKC, full non-Turkic casefold, then NFD. Drop combining
marks after an alphanumeric base in these inclusive hexadecimal ranges:
0041–024F, 0370–052F, 1C80–1C8F, 1D00–1FFF, 2C60–2C7F, A640–A69F,
A720–A7FF, AB30–AB6F. Preserve other combining marks, including Japanese
dakuten. Keep other alphanumeric characters; replace remaining characters
with ASCII space and clear the base's mark-folding flag. Recompose NFC, split
on whitespace, replace whole tokens using expansions once, and join with
one ASCII space. Alphanumeric and mark properties use Unicode 17.0.0.
Empty or longer-than-128-scalar normalized names are invalid.

A names shard has these eight sections, in order:

| Section | Width | Meaning |
| --- | ---: | --- |
| 1 | 1 | FST map from UTF-8 normalized key to zero-based key ordinal |
| 2 | 8 | u64 spelling-row offsets, one per key plus terminal |
| 3 | 20 | Spelling records |
| 4 | 8 | u64 string offsets, including null and terminal |
| 5 | 1 | UTF-8 source spellings |
| 6 | 1 | FST map from UTF-8 trigram to zero-based trigram ordinal |
| 7 | 8 | u64 posting offsets, one per trigram plus terminal |
| 8 | 4 | u32 normalized-key ordinals |

A spelling record is five u32 fields: country reference, state reference,
canonical-city reference, source-spelling string reference, alternate flag.
Country and city references are nonzero; state may be zero. Catalogue
references use the pack's global ID space. Alternate is 0 for primary, 1 for
English/alternate/ASCII. Source spelling must be non-null UTF-8. Strings use
the catalogue's null-offset convention. Key and trigram IDs enumerate strictly
ascending UTF-8 keys within each shard. Row and posting offsets start at zero,
are strictly increasing between entries, and end at their section's record
count (an empty map has the single offset zero). All keys have rows.
Writers order records by key, city ID, alternate flag, then source spelling.
A key may cross shard boundaries; retrieval merges and deduplicates by city.
Current construction admits at most 4 MiB of input strings plus record overhead
per shard, within the shared 512 MiB writer admission budget.

For each normalized key, prepend ^ and append $, then enumerate unique windows
of three Unicode scalar values. Each trigram's posting list contains every
matching key ordinal once, in ascending order. No missing or extra postings
are permitted. Trigram and key FSTs use the following identical wire encoding.

### FST encoding

This is the version-3 map representation emitted by fst 0.4.7. Integers are
unsigned little endian; packed integers use a declared 0–8-byte width
(zero bytes means zero). An FST begins with u64 version=3 and u64 type=0,
followed by encoded nodes. Its final 20 bytes are u64 key_count, u64 root
address, and u32 masked CRC32C of every preceding byte. CRC32C uses reflected
Castagnoli polynomial 0x82F63B78, initial/final XOR 0xFFFFFFFF. The mask is
rotate_right(crc,15)+0xA282EAD8 modulo 2^32. Addresses are byte offsets within
the FST section, pointing at the node's final state byte. Root is the last
encoded node; address zero denotes an implicit final node with output zero
and no transitions, consuming no node bytes.

Transitions consume one input byte and contribute an unsigned u64 output.
A lookup follows the input bytes from the root; success requires a final
node after the last byte. Its value is the sum of transition outputs and that
node's final output, with overflow rejected. Nodes form an acyclic backward
graph. Transitions have distinct input bytes in ascending logical order.

Let A be a node address, V its state byte, and S the first byte of its encoded
node. Three layouts are selected by the top two bits of V:

- 11: one transition, nonfinal, zero output. Low six bits select the common
  input byte below, or zero means a literal byte immediately before V.
  S=A for a common input, otherwise A-1. Target address is S-1.
- 10: one transition, nonfinal. Bytes from S are output (O bytes), target
  delta (T bytes), size byte, optional literal input, V. The size byte's
  high nibble is T and low nibble is O. Input selection is as above.
  Target is zero if delta=0, otherwise S-delta.
- 00 or 01: general node, final exactly when bit 6 is set. Low six bits
  encode transition count N when nonzero. Otherwise the byte before V
  encodes N; value 1 means 256, other values are literal (including zero).
  The size byte immediately precedes that optional count byte or V.
  Its nibbles give T and O as above. From S the fields are: final output
  (O bytes, final nodes only), N outputs in reverse logical transition order,
  N deltas in reverse order, N input bytes in reverse order, an optional
  256-byte input-index table when N>32, size byte, optional count byte, V.
  Each delta gives target zero or S-delta. For N>32, table[input] gives the
  logical transition ordinal; values >=N denote no transition.

The low-six-bit common-input codes 1–63 correspond, in order, to these ASCII
characters (one uninterrupted sequence):

    te/oasripcnw.hlm-du012g=:bf3y5&_4v9678k%?xCDASFIBEjPTzRNM+LOqHG

Readers validate bounds, checksum, graph order, input order and declared key
count before exposing the FST. Map values are ordinal IDs, not byte offsets.
An empty key is not permitted in these name or trigram maps.

### Retrieval, filters and result semantics

Search exact keys first. If no result survives the filters, search keys with
the query as a prefix. If still empty, take trigram candidates having Dice
similarity at least 0.45, then retain those with Levenshtein distance at most
clamp(floor(query scalar length / 4),1,3). Distances count Unicode scalars.
Hard country and subdivision filters precede ranking, phase selection and
candidate truncation. Country is ISO alpha-2; subdivision compares the full
published code case-insensitively. Duplicated spellings yield one city.

Results have kind city, centroid point, centroid's r8 cell, catalogue timezone
when published, and rank_basis population. Primary exact keys use match exact;
English/alternate/ASCII keys use alternate_name. Prefix and typo fallbacks use
fuzzy, distinguished by opt-in evidence reasons name_prefix and name_trigram.
Ties rank by population descending (unknown as zero), then stable city ID.
Multiple surviving cities are ambiguous even if limit=1 truncates the list.
Flat geographic fields remain null. prefer=population explicitly selects the
first candidate; a unique city is matched without that preference.

limit must be 1–100; scope currently accepts only cities. Malformed arguments
and code-shaped queries are invalid_input with the appropriate verb in hint;
street-address-shaped queries are unsupported_granularity. Known exact city
names take precedence over airport/LOCODE and street-word heuristics, while IP,
phone, H3 and purely numeric postal forms remain identifier requests.
The Python geocode_columns method uses the shared candidate-offset layout.

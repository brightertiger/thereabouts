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

## Postal family and shared forward observation index

A postal manifest has family **postal**, zero distance-policy bounds, and
normalization **["strip_ascii", "upper_ascii", "remove_ascii_spaces"]**.
Operations execute in that order: trim ASCII whitespace at the ends, uppercase
ASCII a–z, then remove U+0020 throughout. Do not remove hyphens or infer numbers.
The same operations are applied during export and lookup. Unknown operations or
a different postal rule sequence are incompatible data. The key is the uppercase
two-letter source country, one NUL byte, then normalized postal code. Source
country and the country assigned by the dataset may differ; neither is rewritten.

Each postal pack contains metadata, any referenced catalogue shards, at least
one **exact** artifact, and notices. Catalogue references are local to this pack,
with the same records and global ordering as core. Empty indexes are explicit.
The exporter requires postal_codes, places, canonical_cities,
place_to_city, countries, and subdivisions; fixture exceptions must be
explicit. Catalogue closure includes every assigned country, state and city and
their published relationships. An available place-to-city mapping replaces the
source city's reference. No nearest city or missing coordinate is invented.

Exact artifacts use container kind **4**, with five sections:

| Section | Width | Contents |
| --- | ---: | --- |
| 1 | 8 | N+1 little-endian u64 key offsets, beginning at 0 |
| 2 | 1 | Concatenated UTF-8 compound keys, without terminators |
| 3 | 44 | N observation records in nondecreasing bytewise key order |
| 4 | 8 | First-use string offsets; starts with 0, 0 for null |
| 5 | 1 | Concatenated UTF-8 observation strings |

The terminal key offset equals section 2's length. Every key span is nonempty,
valid UTF-8, and may contain the compound-key NUL. Duplicate keys retain distinct
source observations and may span shards. Readers search all intersecting key
ranges and combine their observations. Shard boundaries do not alter results.
String reference 0 is null. Positive reference r selects bytes between offsets
r and r+1. The final offset equals the string pool length.

Observation records have this shared layout:

| Offset | Type | Meaning |
| --- | --- | --- |
| 0, 4, 8 | u32 each | Country, state, city catalogue references; 0 = absent |
| 12, 16 | i32 each | Source latitude/longitude in microdegrees |
| 20, 24 | u32 each | Source and source_id string references |
| 28, 32, 36, 40 | u32 each | Name, code, scheme and details string references |

Coordinates are either both i32::MIN or within geographic bounds. Source and
source_id are required; details, if present, is JSON text. Postal details retain
admin1/2/3 names and codes, accuracy and source variant. Place name and all
contributing source identities remain available with evidence=True.
The public point is the source point, separately from city.point.

Keys and offsets are retained at open; observation records and strings use
positioned range reads on demand. One **4 MiB cache per pack**, shared by all
exact shards, retains decoded observations. Export emits nominal 4 MiB shards
from typed SQL columns; no dataset row is serialized as a JSON object.

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

The kind-4 exact index and 44-byte observation layout above are reused. Keys
are UTF-8 scheme + NUL + country + NUL + normalized code. Country is the
uppercase two-letter source country. All schemes except local additionally
have a global key with the empty country component. The observation name
is the airport name, code and scheme describe the indexed code, and details
is JSON with type, municipality and region_code (nullable strings).

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
the kind-4 exact index with a full normalized LOCODE as the key, without a
separator. LOCODE has two ASCII uppercase country letters and three uppercase
ASCII letters or digits. Export rejects disagreement between locode,
country_code and location. Lookup accepts the full code or three characters
plus country. Conflicting or malformed country hints are invalid_input.

The shared observation layout stores name, full code, scheme "unlocode", and
details containing non-null name_ascii, subdivision_code, function, status,
iata_code, date, change, remarks and coordinates_raw. Point and geographic
references are published associations with canonical-city rollup, not a new
reverse lookup. Identity is source plus source_id. Kind is trade_location and
match is exact. Duplicate identities merge evidence; multiple identities are
ambiguous. Column output has the shared dictionary and candidate-offset layout.

## Phone family and decimal trie (kind 5)

The phone family requires phone_prefixes, phone_metadata and the five geographic
tables required by postal. The manifest normalization is exactly
["e164_plus", "strip_phone_presentation"]. Input must have a leading plus;
ASCII spaces, hyphens and parentheses after it are ignored. The remaining 1–15
ASCII digits must begin with 1–9. National numbers, extensions and Unicode
digits are invalid_input. This is prefix lookup, not subscriber validation.

A trie shard has four sections: nodes (48-byte records), observations (44-byte
shared records), string offsets (u64), UTF-8 string bytes. Each node contains
ten little-endian u32 child references for digits 0–9, followed by u32 first
observation and u32 observation count. Node zero is the root; child 0xFFFFFFFF
means absent. Every child has a greater node index than its parent, has exactly
one parent, and is reachable from the root. Depth is at most 15. The root has
no observations. Nonempty observation ranges are contiguous, disjoint, cover
the observation section exactly, and reference records for that node's prefix.
The null and terminal string-offset rules are the same as the exact index.
Empty input still emits an explicit root node.

Queries follow digits from the root and retain the deepest terminal reached.
Across shards only terminals at the maximum matched depth contribute records.
No shorter calling-code result competes with a more specific prefix. The writer
sorts prefixes and emits bounded shards; reader observations are range-read and
share the pack's bounded LRU.

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

## IP family and inclusive intervals (kind 6)

The ip family requires ip_ranges and the same geographic tables as postal.
Normalization is ["ip_literal"]. Input is a trimmed IPv4 or IPv6 address literal.
Ports, CIDR suffixes, IPv6 zones and noncanonical IPv4 leading zeroes are invalid.
IPv4-mapped IPv6 literals remain IPv6; the two address families never alias.

Each kind-6 shard has four sections: interval records (36 bytes), shared
observations (44 bytes), string offsets (u64), UTF-8 strings. An interval contains
one u8 IP version (4 or 6), three reserved zero bytes, then 16-byte network-order
start and end addresses. Endpoints are inclusive; IPv4 occupies the low 32 bits
with zero high bits. There is exactly one observation per interval, at the same
row index. Ranges are ordered by (version, start), strictly nonoverlapping,
including across shards in manifest order. Adjacent ranges are allowed. An empty
family still has an explicit empty interval shard. String rules are shared with
the observation index.

Open retains each shard's first and last bounds. Lookup rejects out-of-shard
queries and binary-searches fixed-width bounds using positioned reads. A bounded
1 MiB address-result LRU avoids repeated searches for identical addresses;
observations use the pack's shared range-read cache. Full verification visits
every range and record, enforcing ordering and cross-shard nonoverlap.

The writer requires packed endpoints to agree with the published textual
addresses and ip_version. It rejects overlaps instead of choosing an arbitrary
source. Kind is ip_range, match exact. Source point and canonical geographic
associations are projected. Observation name is the published city text, code
is start + U+2013 + end, scheme is ipv4 or ipv6, and details JSON preserves
country_code, region and city text, including explicit nulls. Source text remains
available in evidence when it differs from canonical country/state/city fields.

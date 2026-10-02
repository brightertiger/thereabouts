# Thereabouts serving packs

A serving pack is an immutable directory containing a JSON manifest, binary
shards and source notices. It preserves answers from verified golden v2 tables;
it performs no geographic reconciliation. This document specifies format 1.0,
`thereabouts-pack-1`, currently for the `reverse` family only. The original
`h3-table-v1` format is unrelated and is not accepted by this exporter.

Export and verify locally, using this checkout's build dependencies:

```sh
python -m build_data.serve export \
  --manifest sample/golden/manifest.json --release sample/release.json \
  --output packs/reverse-sample
python -m build_data.serve verify packs/reverse-sample
```

The golden manifest must be completed `golden-2`, with verified quality,
normalization, canonical-city and place-mapping tables. All listed files are
hashed; relevant Arrow schemas and row counts are checked. Pending spatial or
static joins and failed quality gates are rejected. Other lookup families are
hash-checked but are not exported or interpreted. The exporter never opens the
golden ledger or writes to the source dataset. It is a separate stage, not yet
wired into the world controller.

`release.json` supplies explicit release identity and attribution; it is not
inferred from file names. This is a complete synthetic example (replace the
notice's size/hash with the real values):

```json
{
  "data_version": "synthetic",
  "catalogue_epoch": "synthetic",
  "sources": [{
    "source": "synthetic", "release": "fixture", "license": "public-domain",
    "attribution": "Thereabouts test fixture",
    "source_url": "https://example.invalid/synthetic",
    "license_url": "https://example.invalid/license"
  }],
  "notices": [{"path": "LICENSE.txt", "size": 0, "sha256": "<64 lowercase hex digits>"}]
}
```

Notice paths are relative to this metadata file. Every source entry requires all
six strings shown above and no additional fields; source/release pairs are unique.
Notice records contain exactly `path`, `size` and `sha256`. The exporter copies
these notices and the golden `DATA_LICENSES.md` and `DATASET_CARD.md`. Real release
metadata must account for admitted sources and their licence texts. Copying the
golden draft notice does not establish clearance to redistribute a dataset.

## Manifest and identity

`manifest.json` is UTF-8 JSON, without a BOM. Exporters write sorted object keys,
no insignificant spaces, literal Unicode, and a final newline. Duplicate object
keys and nonfinite numbers are invalid. Unknown optional top-level fields may be
ignored. Format fields are exact; unknown major/minor versions, required flags,
families or dependencies must fail. Booleans are not integer versions or counts.

The manifest identity is SHA256 of the exact file bytes, including its newline.
It is supplied externally by an operator or release index; it is not stored
inside the file. Python verification returns this as `manifest_sha256` in its
detached result. Adjacent hashes provide integrity, not publisher authentication.

Required fields:

| Field | Value or meaning |
| --- | --- |
| `schema`, `format` | `thereabouts-pack-1`; `{major:1, minor:0, required_features:0}` |
| `family`, `minimum_reader`, `dependencies` | `reverse`, `0.1.0`, `[]` |
| `data_version`, `catalogue_epoch` | Nonempty immutable release and identity-epoch strings |
| `reference_resolution`, `block_resolution` | 8, 3 |
| `h3_version` | Exporter's H3 Python version; H3 major 4 is supported |
| `golden_sha256`, `policy_sha256` | SHA256 of input manifest bytes and canonical normalized policy JSON, respectively |
| `nearest` | `{distant_over_m:25000, cutoff_m:50000, exact_distance:false}` for the current policy; numbers are copied from the golden policy, not reader constants |
| `coverage` | `world` or `blocks`, as defined below |
| `place_count` | Number of pack-local places; uint32 range, including zero |
| `sources`, `notices` | Source entries above; list of all notice artifact paths |
| `files` | Ordered artifact records described below |
| `export`, `export_fingerprint` | Deterministic input identity and its SHA256 |

`export` contains `golden_sha256`, the supplied `release` object, `shard_bytes`,
an `implementation` map of repository-relative code paths to SHA256, and `tools`
with Python, PyArrow, SQLite and H3 Python/C versions. Its fingerprint uses the
same canonical JSON serialization, **without** the final newline. Object keys
sort by Unicode scalar value (equivalently UTF-8 byte order), not JavaScript's
default UTF-16 sort. This identity contains only strings, integers, lists and
objects; integer JSON uses decimal notation without an exponent. Strings escape
quotes, backslashes and control characters as JSON requires, leaving other Unicode
literal. Release and
golden fields must agree with the corresponding top-level fields. This object
contains no run timestamps or absolute paths. It is reproducibility metadata,
not a separate client configuration language.

Each file record contains `path`, integer byte `size`, lowercase `sha256`, and
`kind`. Paths are slash-separated relative paths, without empty, dot, parent,
backslash or colon components. Symlink artifacts, duplicate paths and a payload
named `manifest.json` are rejected. Only listed files are consumed.

* `kind: "catalogue"` adds `first_id` and `count`. Ranges are contiguous from 1
  through `place_count`, in manifest order. Empty catalogue shards are absent.
* `kind: "cells"` adds `first_block` and `last_block`. Ranges are disjoint and
  ascending. Directory entries within a range may be sparse.
* `kind: "notice"` has no binary header. Every notice is checksummed and listed
  in `notices`. It is retained with the data, including offline copies.

Catalogue integers have meaning only inside this pack. Join packs using public
place IDs and compatible catalogue epochs, never their integers. The exporter
includes only the transitive closure of cell references through country, parent,
sovereign and normalized-city references. Public IDs are sorted by unsigned UTF-8
bytes and assigned consecutive IDs starting at 1. Reference 0 always means null.

## Binary container

All integers are unsigned **little endian**. No native struct alignment, NPY
header, compression, executable objects or implicit platform padding is used.
Read uint64 fields with `BigInt` in JavaScript. Check bounds before converting to
a host index; the complete span must be representable and within the file.

Every shard begins with this 32-byte header:

| Byte offset | Type | Value |
| --- | --- | --- |
| 0 | 8 bytes | `54 48 45 52 45 50 4b 00` (`THEREPK` plus NUL) |
| 8, 10 | uint16 each | Major 1, minor 0 |
| 12 | uint32 | Required-feature flags, zero |
| 16 | uint32 | Kind: 1 spatial, 2 catalogue |
| 20 | uint32 | Number of section entries: 4 spatial, 3 catalogue |
| 24 | uint64 | Exact total file length |

Immediately following are 32-byte section entries: `type:uint32`,
`flags:uint32`, `offset:uint64`, `length:uint64`, `count:uint64`. Flags are zero.
Sections occur in the order below. Each starts at the next multiple of 8 after
the preceding section (or directory). Padding bytes must be zero. Empty sections
can share an offset. `length = count * record_width`; overflow is invalid. There
are no overlaps, gaps other than alignment padding, or trailing bytes.

| Kind | Section types in order | Record widths in bytes |
| --- | --- | --- |
| Spatial | 1 blocks, 2 keys, 3 values, 4 label dictionary | 40, 2, 1, 16 |
| Catalogue | 5 places, 6 string offsets, 7 text | 64, 8, 1 |

## Spatial shards

A **block** is an H3 resolution-3 logical subtree. Its numerical address is
`((base_cell * 7 + digit1) * 7 + digit2) * 7 + digit3`. There are 41,846 possible
addresses, but only 41,162 valid H3 blocks; pentagon padding is never coverage.
Each directory entry has this packed 40-byte layout:

| Offset | Type | Meaning |
| --- | --- | --- |
| 0 | uint32 | Block address |
| 4 | uint32 | Stored row count, at most 16,807 |
| 8 | uint64 | Byte offset into the keys section |
| 16 | uint32 | Label encoding: 0 flat, 1 uint8 selector, 2 uint16 selector |
| 20 | uint32 | Dictionary label count; zero for flat encoding |
| 24 | uint64 | Byte offset into the values section |
| 32 | uint64 | Byte offset into the dictionary section |

Directory entries are strictly increasing by block. Their three spans are
contiguous in directory order, starting at zero and consuming their sections
exactly. A zero-row directory entry explicitly records a known ineligible block.
It uses flat encoding and consumes no keys or labels. No zero-row block is omitted
from a completed input snapshot.

For stored resolution `r` from 3 to 8, let `d = r - 3` and
`O(d) = (7**d - 1) / 6`. The local uint16 key is `O(d)` plus the base-7 integer
of H3 digits 4 through `r`. Key 0 is the block root; keys never exceed 19,607.
Stored keys must encode actual valid H3 cells, be strictly increasing, and have
no stored ancestor. Sparse uint16 keys are the only key encoding in 1.0; there
is no bitmap encoding yet.

Each 16-byte label is four uint32 values: `country_ref`, `state_ref`, `city_ref`,
`flags`. The city reference is the **final v2 city**, which may be a rural
settlement. There is no independent nearest-place calculation at runtime.

Flags are:

| Bits | Meaning |
| --- | --- |
| 0–2 | City method: 0 null, 1 `city_polygon`, 2 `policy_polygon`, 3 `urban_allocation`, 4 `town_radius`, 5 `rural_polygon`, 6 `rural_nearest`, 7 `rural_nearest_distant` |
| 3 | Country method: 0 null, 1 `area` |
| 4 | State method: 0 null, 1 `area` |
| 5 | Land method: 0 `land`, 1 `offshore` |
| 6–31 | Reserved, must be zero |

Each place field is zero if and only if its method is null. A present row whose
four uint32 values are all zero is **unassigned land**, not an absent row. The
`town_radius` encoding is supported for interpreting input, without enabling the
policy. A distant-nearest answer has distance greater than `distant_over_m` and
at most `cutoff_m`; ordinary rural-nearest is at most `distant_over_m`. Exact
distance remains null. These statements concern represented r8 centres.

Flat encoding stores `count * 16` bytes in values. Dictionary encoding stores
unique labels sorted lexicographically by the **four numerical fields**, not by
their byte strings. Values hold `count` zero-based dictionary selectors of the
specified width. Every selector is below the dictionary count. The exporter
chooses uint8 through 256 labels, uint16 above that, and uses a dictionary only
if `dictionary_bytes + selector_bytes < flat_bytes`; ties choose flat.

For a query, validate an H3 resolution-8 cell. H3 has base-cell bits 45–51,
resolution bits 52–55 and three-bit digits at shifts `3*(15-level)`, for levels
1–15. Derive its block and depth-5 local suffix from those digits. Search keys
`O(5)+suffix`, `O(4)+floor(suffix/7)`, down through key 0, taking the first match.
For coordinates, convert to H3 **at resolution 8 once** before this walk. Never
convert the original coordinate separately at each coarser resolution.

If a valid block is absent from a `blocks` pack's directory, the answer is
`outside_coverage`. Within a listed block, absence of every ancestor is
`ineligible`. A `world` pack must contain all 41,162 valid block entries, including
empty ocean blocks. This coverage distinction prevents a small sample from
claiming that unexported parts of the world are ocean.

## Catalogue shards

Each place record contains sixteen uint32 values, without padding. Its ID is
the manifest shard's `first_id` plus the record's zero-based index. The first
twelve fields reference the shard-local string pool, in this exact order:

```text
place_id, name, name_en, local_name, role, settlement_kind,
country_code, code, code_status, parent_method, normalization_method, evidence
```

The last four fields reference pack-global place IDs, in this exact order:

```text
country_id, parent_id, sovereign_id, normalized_city_id
```

String reference zero is null. The string-offset section contains one uint64
start offset per string, plus a terminal offset, relative to the text section.
Offsets 0 and 1 are both zero, reserving the empty null span. A nonzero string
reference can legitimately have an empty span and means the empty string. All
offsets are nondecreasing, all spans fit, the terminal equals text length, and
each string is valid UTF-8. String IDs are assigned in first-use order within
each shard, deduplicating exact text. They never join across shards.

`place_id`, `name`, `role`, `settlement_kind`, `country_code` and `evidence` are
nonempty. Roles are `country`, `state`, `district`, `city`, `town`, `settlement`.
Settlement kinds and normalization methods retain source strings. Nullable names
and codes are retained without translating, normalizing or inferring them. A
code has only the status recorded by golden; absent code-system evidence must
not be invented by clients.

`evidence` is a JSON object with exactly `golden_table` (data-root-relative
Parquet path), `source_ids` and `name_provenance` (decoded values of those golden
JSON columns). Together with the public place ID and `golden_sha256`, it identifies
the audit row. Source releases and notices are pack metadata. Full raw provenance,
population, geometry, alias lists and map evidence remain in golden Parquet;
readers must not imply that those details are installed. Cell evidence is located
by the stored H3 key and source manifest. No audit lookup performs network access.

## Publication, verification and limits

The default transport target is 64 MiB, configurable with `--shard-bytes`.
Cell groups are bounded using the worst-case flat size per r3 block; catalogue
groups use an upper bound on added strings and records. Headers/alignment and a
single indivisible place/block can exceed the target. Sharding changes storage,
never geography. SQLite holds the build-only catalogue index with a 16 MiB page
cache and disk-backed sorting. Arrow scans project required columns in 1,024-row
batches. See [CLIENT_STATUS.md](CLIENT_STATUS.md) for measured resources; these
parameters are not a proven world-scale RSS or disk bound.

A sibling `.serve-<fingerprint>/` directory owns temporary files and verified
shard receipts. An advisory `.serve.lock` serializes exporters in the output
parent. After interruption, catalogue indexing is reconstructed, completed shard
hashes are checked and valid cell shards are reused. Corrupt/uncommitted shards
are rebuilt. Final verification checks hashes, section spans, UTF-8, sorted keys,
valid pentagon addresses, ancestor disjointness, references and method/null rules.
Every emitted place field and stored cell is then compared with the source
transformation, including on resume; source files are rehashed before publication.

Only then is the directory renamed atomically to the requested output. Repeating
the same export verifies and returns it without modifying payloads or their
mtimes. Changed inputs/code/options need a different output directory. Published
corruption is reported, never overwritten. Interrupted staging directories remain
available for resumption. Completed staging is removed. Code changes create a new
fingerprint; abandoned staging from old fingerprints requires explicit removal.

An open-time reader checks manifest compatibility, file lengths and container
directories. A full verifier additionally scans hashes and payload structure.
Consumers must keep installed files immutable while mapped. The Python
`thereabouts.packs.verify.verify(path)` helper implements full verification;
the primitives under `thereabouts.packs` are internal and are not the planned
public `Geocoder` API. Golden admission trusts the verified manifest and its
quality records; it does not rerun geographic quality adjudication.

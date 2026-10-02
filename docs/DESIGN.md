# H3 table design

The accepted design is one combined H3 resolution-8 table, exactly equivalent to
labelling every finest-resolution cell centre with the source policy below.
Runtime returns `Location(city, state, country, country_code)` or `None`; it needs
only H3 and NumPy. Build-only Shapely/SciPy polygon and nearest-settlement indexes
live in `build_data/reference/` and never ship in the wheel.

## Source policy

The pinned sources are Natural Earth 5.1.1 and GeoNames cities1000, frozen
2026-10-01. Archives, SHA256 pins, attribution and repair/clipping audit are retained.
The reference source pack lives at `data/reference`; the exported combined table
lives at `data/h3-world`. `data/cache` holds the four pinned source archives.

Country/state independently choose the lexically smallest containing Natural
Earth source ID, with closed-boundary tolerance 1e-9 degrees. No snapping or
geopolitical adjudication is performed. Source ISO alpha-2 codes are retained
where valid; placeholders and missing codes remain absent.

Eligibility is Natural Earth land **or country coverage**, including inland water,
ice and Antarctica. Admin1-only coverage cannot create a row. Unassigned land can
return `Location(None, None, None, None)`. Regional packs restrict eligibility to
their closed coverage box.

City is the nearest eligible GeoNames settlement within an inclusive 50 km of the
cell centre, across country borders. Distances are spherical (radius 6371.0088 km);
ties within 1e-9 km choose the lowest GeoNames ID, then apply the cutoff to that
record's actual distance. Identical public city names share a string ID.

The current-settlement allowlist is `PPL`, `PPLA`, `PPLA2`, `PPLA3`, `PPLA4`,
`PPLA5`, `PPLC`, `PPLF`, `PPLG`, `PPLL`, `PPLR`, `PPLS`, `STLMT`. These cover
populated places/localities, administrative seats, capitals, farming/religious
villages and settlements. Sections (`PPLX`), historical capitals/places (`PPLCH`,
`PPLH`), abandoned (`PPLQ`) and destroyed (`PPLW`) places are excluded; unknown
codes are excluded too. The rule follows the [GeoNames feature-code list](https://www.geonames.org/export/codes.html)
and is recorded in both manifests. A stale reference policy is rejected by the
builder instead of silently reusing an unfiltered catalogue.

Lower Manhattan `(40.7128, -74.0060)` returns New York City; Tokyo's catalogue
centre `(35.6895, 139.6917)` returns Tokyo. At `(35.6762, 139.6503)`, the former
Eifuku (`PPLX`) answer becomes Asagaya-minami (GeoNames 1865090, **PPL**). That
record remains a nearer competitor inside Tokyo. The filter cannot guarantee
municipal city names where the source labels a district as a current populated
place; there are no city-name exceptions. Amsterdam now returns Amsterdam.

## Conservative refinement without labelling every fine centre

The builder streams one resolution-3 subtree at a time: at most **16,807** fine
centres at resolution 8. It **enumerates all actual descendant coordinates** with
H3, including pentagon descendants, then takes their min/max latitude/longitude.
This is deliberate: it avoids any assumption that descendants lie in the parent's
hexagon, any empirical radius bound, or an unproved enclosure at an icosahedron
face seam. World coordinate enumeration is 691,776,122 centres; coordinate
conversion is much cheaper than polygon/settlement labelling. No flat world label
array is retained in RAM or written to disk.

Starting at resolution 3, each subtree is certified as follows:

1. The rectangle encloses every actual finest-resolution descendant centre.
   An STRtree tests it, expanded by twice the containment tolerance, against **all
   polygon boundaries**, including holes, islands, overlaps and coverage edges.
   Boundaries are split into overlapping 64-segment pieces without simplification.
   With no boundary intersection, all containing polygon identities are constant
   on the connected rectangle. Seam/pole rectangles are conservatively refined.
2. Label the rectangle midpoint. A meridian/parallel route bounds the distance
   from it to every rectangle point by
   `R = earth_radius * radians((north-south + east-west)/2)`, with a numerical margin.
   If the nearest settlement distance minus R exceeds 50 km, city is absent
   everywhere. Otherwise require nearest distance plus R below 50 km and the
   nearest/second-nearest distance gap greater than 2R plus tie/numerical margins.
   The triangle inequality then proves that the same settlement wins everywhere.
   Co-located competitors cause extra refinement, never an unsafe certificate.
3. If either proof fails, refine. At the finest resolution, label each unresolved
   centre with the vectorized oracle. Collapse identical sibling answers again
   afterwards; this removes false-positive refinement caused by loose envelopes.

The batch polygon path uses prepared containment and a separate short-boundary
index for tolerance; the nearest path uses vectorized unit-sphere cKDTree queries,
atan2 distances and a complete tie-radius search for exceptional rows. The scalar
reference does not use these polygon candidate optimizations.

For the regional fixture only, a finest-resolution H3 fill of its slightly outward-expanded coverage box
selects the resolution-3 roots to enumerate; complete descendant subtrees are
then processed, including their outside-region centres. Default tests enumerate
and label **all 554,631 cells** in these roots independently of the certificates,
and compare every label with the generated hierarchy and scalar and batch lookup.
World tests additionally exercise all resolution-3 pentagons, poles, the seam,
random points, and direct source polygons. Sampling is additional evidence, not
a substitute for the certificate argument or exhaustive fixture check.

## Mmap format

`src/thereabouts/format.py` is the shared executable definition for schema
`h3-table-v1`; the builder and reader import its constants and label codec.
All multi-byte integers are **little endian**. Files contain no Python objects or
pickles. Only the combined layout is supported.

**Blocks and local keys.** The fixed directory has `122 * 7**3 = 41,846` rows.
A block is an H3 resolution-3 logical subtree, addressed by the H3 base-cell number
followed by the first three base-7 digits. Unused pentagon addresses stay empty.
Within a block, depth `d = resolution - BLOCK_RESOLUTION` has level offset
`O(d) = (7**d - 1) // 6`. Its key is `O(d)` plus the base-7 integer formed by the
remaining H3 digits. The root key is zero. At resolution 8, all ancestor levels
fit into keys 0 through 19,607, including unused pentagon slots.

`combined-directory.npy` is a one-dimensional NPY array with this packed 21-byte
record (no alignment padding):

| Field | Type | Meaning |
| --- | --- | --- |
| `keys` | uint32 | Offset into the key file in **uint16 elements** |
| `values` | uint32 | Byte offset into the value file |
| `dictionary` | uint32 | Offset into the dictionary in **uint64 elements** |
| `count` | uint32 | Number of stored local keys/values |
| `labels` | uint32 | Number of entries in this block's dictionary |
| `width` | uint8 | Low two bits: value width (1 or 2 bytes); bit 7: bitmap flag |

A zero count means no stored answer in the block. Other width bits are reserved
and must be zero. Stored cells are disjoint: no stored key has a stored ancestor.
Zero labels are omitted, including all-ocean blocks.

**Sparse versus dense keys.** `combined-keys.bin` holds either a sorted uint16
key list (`count` elements), or a ranked bitmap. Let `D` be the finest depth and
`W = ceil(O(D+1)/64)`. A bitmap consists of **W uint64 words followed by W uint16
prefix ranks**; ranks are not interleaved. The low bit of a word is its first key.
Rank `i` counts all set bits strictly before word `i`. If key `k` is present, its
value position is `ranks[k//64] + popcount(words[k//64] & ((1 << (k%64))-1))`.
The bitmap is selected only if its `10*W` bytes are smaller than the sparse list's
`2*count` bytes. At resolution 8, W is 307 and a bitmap occupies 3,070 bytes.
Bitmap addresses use the same uint16 offset unit as sparse lists, so a uint64
word occupies four key elements. Neither layout requires a global fine-cell array.

**Values and dictionaries.** `combined-values.bin` stores local dictionary IDs in
ascending-key order, uint8 for up to 256 dictionary entries, otherwise uint16.
`combined-dictionary.bin` stores each block's sorted unique uint64 labels. Both
paths validate value spans and dictionary references through one decoder.

**Labels and names.** For a present row, country/state are zero-based catalogue
indices with -1 for a missing field; city is a string ID with zero for missing:

```text
admin = 1 + ((country + 1) << 16) + (state + 1)
label = (admin << 32) | city
```

The added one preserves present land with no country/state. Label zero means no
row. To unpack, subtract one from `label >> 32`, recover the two 16-bit fields,
then subtract one from each field; city is the low 32 bits. `pack_label` is the
builder's sole encoder and `unpack_label` is shared by the oracle and reader.
`catalog.json` holds country name/code pairs and state names. City strings are
UTF-8 in `city-text.bin`; `city-offsets.bin` holds uint32 byte offsets, including a
terminal offset. City ID zero has an empty span. `manifest.json` records schema,
resolution, eligibility, settlement selection, source hashes, reference-manifest
hash, and every payload's size/checksum. `DATA_LICENSES.txt` travels with the pack.

**Lookup.** Convert at the finest resolution, derive its logical ancestor keys,
and search from finest to coarsest; computing H3 directly at a coarse resolution
would change answers. Batch lookup separates directory selection, ancestor search
and decoding. Scalar lookup avoids batch allocation while sharing H3 addressing,
bitmap offsets, value decoding and label unpacking. Sparse search and bitmap rank
lookup are separate functions with explicit contracts.

The earlier layout experiment measured 17.36 MB admin + 38.23 MB city versus
51.22 MB combined, excluding shared files; this historical comparison selected
combined storage, and the experimental layouts/scripts have been removed.

## Verification and lifecycle

Open checks manifest, sizes, NPY headers and directory shape without scanning
millions of rows. Names decode lazily into a bounded cache. Full verification
checks hashes, key ordering/ranks, ancestor disjointness, dictionary references
and text offsets. The builder verifies a temporary pack before atomic publication;
existing output directories are never overwritten. Data must stay immutable while
mapped. Rebuilding from the final eligibility policy replaces the former audit.

`reverse_many` reads at most 4,096 coordinates ahead and preserves order. mmap
access is protected once per chunk; yielded Locations own their strings. A cheap
closed-flag check keeps the existing contract that closing immediately invalidates
buffered iterators, without reacquiring the lock for each item. `info()` returns a
detached manifest. Close is idempotent; later operations raise `ClosedGeocoderError`.
Coordinates must be finite real values within WGS84 bounds; strings and booleans
are rejected. +180 normalizes to -180. Each process should open its own instance.

## Reproduction

```sh
uv sync
uv run python -m benchmarks.build_size --reference data/reference --data data/h3-world
uv run python -m benchmarks.accuracy
uv run python -m benchmarks.runtime
uv run python -m build_data.verify data/h3-world
uv run pytest
THEREABOUTS_WORLD_DATA=data/h3-world uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy
```

The build-size command builds the reference pack if absent, then builds/verifies
the table and measures complete installed and ZIP sizes. For a plain build use
`uv run python -m build_data --reference data/reference --output data/h3-world`.
Use fresh output paths, or remove previous generated outputs before rebuilding.
Retain `data/cache`: the pinned daily GeoNames archive may no longer be downloadable.

To regenerate fixtures, remove the two existing fixture directories, then run:

```sh
uv run python -m build_data.source_pack --output tests/fixtures/reference --bbox 2 49 8 54
uv run python -m build_data --reference tests/fixtures/reference --output tests/fixtures/benelux
```

The regenerated fixtures total **2,176,949 bytes**, with the original Benelux
region retained. The three benchmark reports each identify the final table by
manifest hash. Accuracy also records the reference hash, workloads and seeds;
its reproducible runtime points live at `data/benchmarks/points.npy`.
See [EVALUATION.md](EVALUATION.md) for final measurements and their limits.

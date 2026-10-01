# Phase 1 reference engine decisions

This implements M2 with the owner's phase-1 changes: Python 3.11+, NumPy/Shapely/
SciPy at runtime, an explicit directory pack, no Rust, `.pog`, H3, data wheel,
implicit installation, download-on-error, municipality API or city alias. The
public dataclasses, aliases, signatures and statuses in IMPLEMENTATION_PLAN.md
are retained. `uniform_cell` remains a reserved public method literal; this
engine returns only `polygon` and `none`. Engine exceptions are exported:
`GeocoderError`, `DataNotInstalledError`, `UnsupportedSchemaError`,
`DamagedPackError`, `ClosedGeocoderError`. Invalid query inputs raise `ValueError`.

## Frozen source and normalization policy

- Snapshot: Natural Earth 5.1.1 (archive version/date 2022-05-08), GeoNames
  cities1000 archive dated 2026-10-01. Retrieval date is recorded; exact original
  retrieval time and boundary validity years were unavailable and are not invented.
  All four URLs and expected SHA256 hashes live in `build_data/sources.py`.
  Today's upstream daily/latest URL is not promised to retain a frozen archive.
- Use Natural Earth's default country/territory worldview, including dependencies
  and Antarctica. Preserve overlapping identities rather than choosing a claim.
  This is not a sovereign-recognition policy. Country IDs use namespaced `NE_ID`;
  admin1 IDs use namespaced `adm1_code`. Names retain source Unicode.
- Exclude admin1 `+00?` placeholder IDs and unnamed rows: 40 world records.
  Missing admin1 is `no_coverage`; only Antarctica and Vatican City have explicit
  `not_applicable` policy when no genuine subdivision contains the point.
  Other incomplete territories are not assumed to lack administrative divisions.
- Country codes use valid two-letter `ISO_A2_EH` values. Admin1 uses source
  ISO-formatted `iso_3166_2` values; temporary `~`, negative and missing codes
  become `None`. Unassigned `XK` codes are also omitted. GeoNames codes remain
  unmodified and are never substituted for polygon classifications.
- Repair invalid geometry with GEOS `make_valid`; retain polygonal components,
  holes and source identities, clip to WGS84 bounds, and explode multipolygons.
  No additional simplification. The pinned sources already split the dateline;
  unexpected unsplit ring jumps fail the build. Longitude-spanning polar closure
  edges are retained. Every invalid-geometry repair is logged (two in this snapshot).
- Source parent keys are linked and child geometry is checked against parent
  geometry. There are 1,019 nonzero differences above 1e-12 square degrees in the
  world snapshot; their individual area fractions are recorded in the manifest.
  Independent source boundaries are preserved, not snapped or reassigned.
- Land means the union of Natural Earth land and administrative coverage, evaluated
  without dissolving identities. This retains inland water covered by either
  administrative layer and ice/Antarctica. `outside_mask` is not a definitive
  ocean or water classification. Unassigned areas inside land remain `no_coverage`.

## Query and numerical policy

- Latitude/longitude order is explicit. Accept real finite numbers in [-90,90]
  and [-180,180]; reject booleans, strings and out-of-range values. Normalize +180
  to -180 in results. Pole longitudes remain in the result, but geometric and
  spherical queries treat all pole longitudes as the same physical point.
- Closed polygon containment includes every part within **1e-9 degrees** in the
  source longitude/latitude plane. This is a numerical tolerance, not a uniform
  metre buffer or an accuracy claim. Dateline queries examine both seam copies;
  exact pole queries examine the polar closure. Deduplicate source identities
  and order candidates lexically by ID. Matched results have one candidate and
  a value; ambiguous results have all candidates and no chosen value. Empty
  results have `method="none"`.
- Settlement search uses a complete cKDTree query on unit-sphere Cartesian
  coordinates. A radius query gathers every possible distance tie and final
  distances use atan2(cross product norm, dot product). Radius **6371.0088 km**;
  distances within **1e-9 km** are treated as ties, resolved by lowest GeoNames ID.
  The selected record's actual distance is returned; the cutoff is inclusive.
  All cities1000 populated-place records are retained, including PPLX records.
- `include_place` must be a boolean; cutoff validation also applies when it is
  false. `disabled` takes precedence over outside-land/no-coverage place status.
  Missing settlements on supported land produce `no_coverage`. No cross-border
  restriction or ellipsoidal-distance claim is made.
- `reverse_many` consumes one pair at a time with no read-ahead, yielding in order.
  Coordinate and option validation occur when the iterator advances. It delegates
  to scalar lookup, so it has bounded memory and identical semantics; vectorized
  batch acceleration is deferred. Empty batches still validate options/lifecycle.
- `close()` is idempotent; queries, iteration, `info()`, `verify()` and entering a
  closed context raise `ClosedGeocoderError`. Construct a new object to reopen.
  One instance serializes concurrent calls and close with a reentrant lock.
  Processes should open their own instances. The default helper retains its first
  selected pack for that process; changing the environment is not a live update API.

## Regional fixture completeness

The included Benelux fixture covers `[west=2, south=49, east=8, north=54]` including
nearby French/German territory. It is cartographic Natural Earth data, not the
higher-detail gbOpen M1 pilot. Its 46 admin1 geometries are clipped to this box;
country metadata retains the global source catalog, with only intersecting
geometries stored. The inclusive coverage box is authoritative: queries outside
it receive `unknown` land and `no_coverage` administration/places.

A naive geographic cut of the settlement catalog would break unlimited nearest
search. Instead the builder partitions the box into cells no wider than 0.25°.
For each center, find its global nearest distance d and bound the distance to
any cell point by R (half the latitude span plus half the longitude span, in
radians). For any query q in that cell, some settlement is within d+R; any record
that could beat or tie it is within d+2R of the center. Keep every record in this
closed spherical ball, including the numerical tie margin. The union of these
candidate sets is therefore globally complete for all covered points, for any
cutoff including `None`. No finite maximum query distance is silently imposed.
The fixture retains 7,681 settlements and is reproducible with:

```sh
uv run python -m build_data --output data/benelux-copy --bbox 2 49 8 54
```

Synthetic test packs separately exercise shared edges, overlaps, enclaves, tiny
multipart islands, coverage gaps, nonapplicability and exact/co-located ties.
They are clearly identified as synthetic and are generated locally without network.

## Format, integrity and lifecycle

Schema `1`, policy `ne-geonames-reference-v1`: `manifest.json`, read-only `.npy`
arrays and `DATA_LICENSES.txt`. Arrays use explicit little-endian numeric dtypes;
there are no object arrays, pickles or serialized private tree layouts.
`text.npy` is a UTF-8 byte pool indexed by uint64 `text_offsets.npy`; country,
admin1 and settlement tables reference strings by uint32 index. Settlement IDs
are int64, coordinates/unit vectors float64. Each of country/admin1/land has a
WKB byte array, uint64 offsets and int32 owner references. Admin1 parent rows
are int32 (-1 unknown); country subdivision state is 0 unknown, 1 not applicable,
2 source subdivisions present. `schema.py` is the canonical dtype definition.

Opening validates manifest, schema/policy, file sizes, array headers/dtypes/shapes,
all offsets and record references while mapping arrays with `mmap_mode="r"` and
`allow_pickle=False`. It neither decodes all strings/geometries nor creates Python
record dictionaries. Geometry and settlement contents are checked when their
indexes are first needed. `verify()` streams every array checksum, validates all
UTF-8, geometry and settlement structures. Pack directories must remain immutable
while open; install updates at new paths. The builder verifies a temporary pack
before publishing the directory and refuses to overwrite an existing destination.

The reference engine lazily retains full prepared STRtrees and a cKDTree rather
than implementing the plan's eventual bounded geometry cache/native indexes.
The direct `PolygonIndex` is isolated from administrative policy so a future
accelerator can precede it without changing public results. Current memory/first
query costs are measured, not hidden behind the mmap/open-time figure.

Strict mypy checks runtime, builder, benchmarks and tests with Python 3.11 syntax.
The only missing-import-stub exceptions are SciPy's spatial module and build-only
pyshp, listed in pyproject.toml. NumPy <2.4 and SciPy <1.17 keep the dependency range
compatible with the Python 3.11 baseline/stubs; the exact tested environment is
locked in `uv.lock`. The lock file is the reproducible builder toolchain.

## Measurements and validation

See `benchmarks/results.json` for machine-readable results and machine/toolchain
metadata. On Apple M2, macOS 27 arm64, CPython 3.12.8, one thread, warm OS cache:

| Measurement | Observed |
| --- | ---: |
| World pack logical bytes | 50,871,792 (50.87 MB) |
| World pack allocated filesystem bytes | 50,917,376 |
| Build, local pinned cache including verification | 7.48 s |
| Geocoder open, median of 20 | 2.68 ms |
| First query after open, excluding import/open | 356.88 ms |
| Warm scalar median / p99, 10,000 land points | 134.08 / 468.92 µs |
| Streaming batch throughput, same 10,000 points | 6,053 points/s |
| Peak benchmark process RSS (including harness) | 260,112,384 bytes |
| Benelux fixture logical bytes | 848,037 |

Random sampling is area-uniform on the sphere, rejection sampled against the
normalized terrestrial mask, including Antarctica, seed 20261001. It uses full
public result construction and the 50 km default cutoff: 5,187 matched settlements,
4,813 beyond-distance results. These counts describe this workload, not accuracy.
Index creation is excluded only from the explicitly *warm* lookup measurements.
Build time excludes downloading because the verified original archives were cached.

The provisional plan's <50 µs median, 100k points/s batch, <150 ms first-result and
<150 MB RSS goals are not met. Warm open and p99 meet their proposed thresholds.
No cold-filesystem timings, dependency footprint, benchmark against competitors,
independent geographic accuracy/adjudication, Linux/Windows testing or published
wheel matrix is claimed. M1's gbOpen comparison, H3 and native performance work
remain later/separate tasks.

Executed validation on CPython 3.12.8: fixture-only `uv run pytest` (66 passed,
14 world tests skipped), and `PYOFFLINEGEOCODER_WORLD_DATA=data/world uv run pytest`
(80 passed). The world suite includes 304 points compared against direct original
Natural Earth geometry and 124 requested world haversine-oracle points (only mapped
land is eligible), along with the regional oracle and synthetic topology cases.
The default fixture suite blocks network connections. Strict mypy, Ruff lint and
format checks pass. `uv build` produced an engine-only wheel, installed and queried
from outside the checkout on CPython 3.11.12; the full 80-test suite also passed
against that installed wheel. Only macOS arm64 was exercised.

A second world build and a second Benelux build were compared file by file;
every SHA256 was identical, including manifests and license notices. Build timing
is printed outside the pack so elapsed time cannot change pack identity. No git
commit, branch change, push, PR or merge was performed; review/commit is left to
the owner as requested.

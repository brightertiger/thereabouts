# Native coordinate contract fixtures (version 1)

`vectors.json` is owned by coords-core. Consumers read it without rewriting it.
It is deliberately outside the root `*-vectors.json` legacy-pack discovery pattern.
Each case has `id`, a key into `sources`, a strict wire `input`, an `expected`
query subset, a per-field absolute `tolerance`, and `footprint_semantics`.
`expected.error` is a stable coordinate error code. Otherwise `expected.normalized`
is the canonical geodetic point in `query`; other expected keys also belong to
`query`. Unlisted fields are tested separately in Rust. A tolerance path uses `*`
for array elements. Fields without a tolerance require exact numeric or structural
agreement (JSON integers and equal floating-point numbers denote the same value).
Longitude error uses the wrapped difference. Schema, status, strings, conversion
IDs and error codes are never tolerance-compared.

`forward_ecef` and `forward_utm` are additional independent projection checks,
with explicit metre tolerances. These are synthetic reference points, not surveyed
station observations. Full-precision coordinates and numeric limits are retained;
none were fitted to the native implementation.

## Offline evidence actually reproduced

- pyproj 3.7.1 / PROJ 9.5.1, `always_xy=True`, `PROJ_NETWORK=OFF`: EPSG:4979 to
  EPSG:4978, EPSG:4326 to EPSG:326xx/327xx, and inverse EPSG:32661/32761 for UPS.
  Includes negative, LEO/GNSS/GEO/100,000 km heights, zone edges and UTM limits.
  The brief's earlier pyproj 3.8.0 / PROJ 9.8.1 provenance is not attributed to this
  run; the installed oracle here is the version above.
- Cached s2sphere 0.2.5 plus cached future: six face centres and seeded cells at
  every level 0–30, using `CellId.from_lat_lng(...).parent(level)` and
  `Cell.get_center()` / `Cell.get_vertex(i)`. No packages were installed.
- Independent integer bit intervals for geohash, arithmetic OLC pair/grid digits,
  DMS arithmetic and NMEA bytewise XOR. The common GGA candidate checksums to 47.
- Analytic WGS84 axes, Greenwich ENU basis, geodetic/ECEF seeded residual checks
  and UTM forward/inverse properties. Seeded properties complement independent
  vectors; round trips alone are not treated as an oracle.
- H3 centres and boundaries were independently reproduced with cached h3-py 4.5.0
  (C H3 4.5.0), `cell_to_latlng` / `cell_to_boundary`, including r0–r8 and a
  pentagon. Rust additionally checks cached h3o 0.9.5 against exact legacy
  `Pack::from_h3` results; that separate assertion is compatibility evidence.

The `sources` object attaches the requested authoritative URLs and records whether
an oracle was actually run. No URL was fetched. EPSG GN7-2 method 9602 remains a
candidate worked example: publication edition/page and reported centimetre
rounding have not been authenticated. GeographicLib MGRS lettering (especially UPS
letter tables), upstream OLC tests, and standard editions still need publication
or upstream-test authentication. PROJ independently checks the MGRS cell projection
coordinates, but does not independently validate the MGRS letters. A published
surveyed-station fixture with WGS84 realization and epoch remains a release evidence
gate; neither Paris nor the EPSG worked example substitutes for it.

## Semantics and implementation choices

Named geodetic input remains the default. Aliases canonicalize to `geodetic`.
All conversion APIs and validation live in Rust. Pure helpers do no IO. Only the
two reverse adapters take a Pack; they leave legacy LookupResult fields unchanged.
Their extra `query` object is present without `evidence=true`, and identifies the
exact input or decoded cell centre separately from `result.point` (H3 query-cell
centre) and `city.point` (catalogue anchor). H3 resolutions 0–8 retain the legacy
stored-ancestor lookup; finer H3 inputs are invalid.

No HDOP-to-metres conversion, uncertainty combination, lookup policy, resolution,
ranking, data or pack changes are made. Cell boundaries are ordered and unclosed.
`radius_m` is the largest centre-to-listed-vertex spherical distance using
R=6371008.8 m; it is neither measurement accuracy nor a curved-edge guarantee.
MGRS grid size is the projected square side; geohash/OLC half-spans are angular.

Canonical height exists only for supplied ellipsoid height or MSL plus explicitly
supplied separation. Other source heights remain metadata. Geodetic origins alone
assume absent height zero; their original object is retained. Explicit geodetic
pole longitude orients local axes, while ECEF pole origins are refused. ECEF inverse
uses Bowring plus bounded Newton refinement and a forward residual below 1 mm.
The entire deep-interior evolute envelope (geocentric radius <= a*e²/(1-e²), about
43 km) is conservatively refused instead of choosing among ambiguous normals.
No latitude is clamped; UTM domain comparisons allow only 2e-12 degrees of numerical
roundoff at exact band/cutoff boundaries. Explicit UTM zones remain honored; MGRS
additionally checks intersection with its zone/band designation, including Norway
and Svalbard. It admits valid squares with centres outside the named band.

Wire text is bounded (general 1024 bytes; MGRS 64; WKT/DMS 256; frame-specific cell
limits). Unknown keys and origin recursion are rejected. Datum labels are metadata,
not vertical transformation commands. Ordinary input errors return `invalid_input`,
actionable hint and `query.error`; pack failures still propagate as pack errors.

## Integration issues

The fixed vocabulary was read and left unchanged. Its phrases describing cell sizes
as uncertainty and optional cell extras are interpreted according to the brief's
more precise rules: decoded extent stays distinct from measurement uncertainty,
and S2 is unconditional native code. This is not a request to change vocabulary.
The two supplied planning-document paths under `thereabouts-coords-plan` were absent
in this checkout environment; implementation used the reproduced version-one contract.
The remaining consumer gates require real PyO3/WASM/CLI integration; core tests do
not establish Python, Node 22/24, or remote CI success.

## Local gate record (2026-10-05)

Rust/cargo 1.99.0, one build job, offline/locked modes, shared target only.
`cargo fmt --check` passed. Clippy `-p thereabouts-core --all-targets --all-features
-- -D warnings` passed. Full `cargo test --offline --locked -p thereabouts-core`
passed: 82 tests, zero failed/ignored, including 21 coordinate test groups.
The coordinate groups include 380 machine-readable fixtures (the final 12 H3
fixtures were added and the coordinate tests rerun after the full suite).
`cargo check --offline --locked -p thereabouts-core --target
wasm32-unknown-unknown` passed. No WASM execution or binding/CLI integration was
claimed from a target check. No remote CI or Python/Node 22/24 matrix was run.

A bounded debug-profile 10k geodetic→ECEF→geodetic→ECEF loop took 12.755 ms;
maximum residual 4.547296321292856e-8 m. `/usr/bin/time -l` reported 0.02 s wall,
3,293,184 bytes maximum RSS for the test process. Free disk remained above 35 GiB
at completion; shared target was about 1.9 GiB. No second target or target clean
was used. Cargo's target lock serialized a run behind a sibling build.

Source changes stay within owned paths; scratch and logs are under `.cache/`.
An initial oracle import created two Python bytecode files in its shared uv cache;
those exact newly-created files were relocated to worktree `.cache/oracle-bytecode/`
and subsequent oracle runs disabled bytecode writes. No dependency was installed,
no data or pipeline was changed/run, and no network/git publication action occurred.
All changes are uncommitted on `wp/coords-core`.

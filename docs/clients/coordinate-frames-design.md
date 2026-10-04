# Native coordinate input design

Planning contract, 2026-10-05; no product implementation is included. The fixed
[shared vocabulary](../../../georeconcile-work/frames-vocabulary.md) controls
frame names and units. Thereabouts converts one declared position to WGS84, then
uses its existing published H3 lookup. GeoReconcile owns conflation, arbitrary
CRS transformations and covariance modelling. No pack, dataset or pipeline change
is needed. All conversion and input-domain validation lives in Rust once.

## Unchanged by default

- Keep Rust `Pack::reverse(lat, lon, evidence)` and `Pack::from_h3`, Python
  `reverse(*, lat, lon, evidence=False)`, `reverse_many`, `reverse_columns`, Node
  `reverse`, `reverseMany`, `fromH3`, MCP `reverse`/`h3`, and legacy CLI calls as-is.
  Do not add a `frame` parameter to the old scalar signatures. Add separate APIs.
- Existing result JSON keys, omission rules, statuses, hints, NumPy columns, CLI
  default columns and golden vectors stay identical for these calls. Existing
  `result::Point`, Python `results.Point` and TypeScript `Point` keep their meaning.
- `result.point` is the **query H3 cell centre**, including on ordinary misses;
  it is not the supplied location. `city.point` is the catalogue anchor. Neither
  becomes the converted point. New results add `query.normalized` for that point.
- No frame is inferred from numeric pairs/triples or a free-form identifier.
  An omitted frame means geodetic only. Text decoding also requires an explicit
  frame in this first implementation; syntax detection is optional in the vocabulary.
- Height and uncertainty do not alter H3 resolution, match, nearest-distance bands,
  ranking or coverage. Coordinates do not establish an address or an area-wide match.

## Coverage and conversion policy

| Frame | Today | Additive native behaviour |
| --- | --- | --- |
| `geodetic`; aliases `latlon`, `lla`, `llh` | Named 2D WGS84 degrees | Optional height, datum and uncertainty in new API; canonical provenance label `geodetic` |
| `ecef` | Absent | WGS84 Cartesian metres; forward and inverse, Bowring seed plus bounded refinement and forward residual check |
| `enu`, `ned` | Absent | Rotate/translate through ECEF at explicit geodetic/ECEF origin; NED maps to ENU `(e,n,-d)` |
| `utm` | Absent | WGS84 Krüger series through order n^6; zone 1–60, hemisphere N/S or latitude band; inverse required, forward helper for tests |
| `mgrs` | Absent | WGS84 UTM and polar UPS MGRS decoder; 100 km square plus 0–5 digit pairs; cell centre and precision footprint |
| `geohash` | Absent | Base-32, 1–12 characters, accept ASCII upper/lower case; exact decoded bounds, centre and angular half-sizes |
| `pluscode` | Absent | Full OLC, padded coarse codes and short codes with explicit geodetic reference; valid pair/grid lengths up to 15 significant characters |
| `h3` | Existing `h3o`, stored-ancestor queries r0–r8 | New frame API retains that same r0–r8 lookup, adds input-cell centre/boundary/uncertainty; r9–r15 return invalid input with guidance |
| `s2` | Absent; no existing Thereabouts extra | Small native face/Hilbert cell decoder, levels 0–30, using u64; query its centre, report its footprint; no new crate |
| `dms` | Absent | Latitude then longitude with N/S and E/W; support degree/minute/second marks or spaced form with comma; no locale guessing |
| `nmea` | Absent | GP/GN talkers with GGA, RMC, GLL; checksum mandatory, active fix mandatory; position/height/DOP/fix metadata |
| `geojson` | Absent | Explicit Point coordinates `[lon,lat]` or `[lon,lat,height]`; no Feature/collection/legacy `crs` member |
| `wkt` | Absent | `POINT (lon lat)` or `POINT Z (lon lat height)`; case-insensitive keywords; no M, ZM, EMPTY, SRID or non-Point geometry |
| `crs:<EPSG or WKT>` | Absent | Refuse, even for an EPSG synonym of a native frame; point at GeoReconcile `crs:` / pyproj and the native label |

The implementation packages cover all native rows above, including S2 and UPS
within MGRS; they must not quietly advertise partial support. S2 has no optional
dependency to preserve here. Do not add a PROJ/geodesy crate or native runtime.
No ECI, datum/epoch transformations, geoid grids, GNSS ephemerides, velocity or
attitude conversions are included. `llv` is not a frame alias: name `enu` or `ned`.

Use `a=6378137 m`, `f=1/298.257223563`, `b=a(1-f)` and f64 throughout.
For ECEF inversion require a forward residual below 1 mm; test heights -10 km
through 100,000 km, including LEO/GNSS/GEO. Reject the geocentre and nonunique
deep-interior solutions or failed convergence; do not extrapolate an invalid
latitude. Poles use longitude zero for ECEF-derived positions; a geodetic pole
origin retains its explicitly supplied longitude to orient the tangent axes.
Reject an ECEF origin exactly on a pole for ENU/NED: it provides no azimuth; ask
for a geodetic origin with longitude. Derived longitudes wrap to [-180,180);
explicit geodetic input accepts both endpoints as today. Never clamp latitude.
Absent geodetic-origin height explicitly assumes ellipsoidal zero and records
`origin_height_assumed_zero`; an explicitly nonellipsoidal origin without known
separation is refused. ENU/NED is a Cartesian tangent frame, not a flat-Earth
surface-distance approximation, even for large offsets.

UTM input requires latitude within [-80,84] after inverse conversion, a valid
zone and consistent hemisphere/band; bands C–X exclude I/O, X spans 72–84.
Use easting [100000,900000] m and northing [0,10000000] m as admission bounds,
then validate inverse output/band. Explicit zones are honoured even where a
neighbouring zone is normally selected; forward automatic zone selection uses
Norway/Svalbard exceptions. MGRS additionally validates allowed zone/band/square
combinations, the 2,000 km northing cycle, precision, southern false northing
and UPS A/B/Y/Z squares. For coarse MGRS, validate square/band intersection,
not just centre containment: a valid edge square can have its centre in the
next latitude band. Do not treat an MGRS lower-left corner as its centre.
No standalone `ups` label is added to the fixed vocabulary.

DMS minutes/seconds are [0,60); latitude/longitude bounds apply after parsing;
reject sign/hemisphere conflicts, repeated axes and extra text. NMEA XORs bytes
between `$` and `*`, accepts exactly two checksum hex digits and optional CRLF,
validates ddmm/dddmm minute bounds, hemisphere, RMC/GLL status and GGA quality.
No unchecked sentence fallback or merging of different timestamps occurs.
GGA `h = altitude_MSL + geoid_separation` is permitted only with valid metre
units and both values; otherwise retain the supplied altitude with datum `msl`
and leave canonical ellipsoidal height absent. Preserve HDOP, fix quality,
satellites and UTC field; do not mistake RMC course for frame orientation.

## Stable Rust contract (contract version 1)

Add `pub mod coords;` in `thereabouts-core/src/lib.rs`. Everything below lives
under `thereabouts_core::coords`, implemented in `src/coords/`. There are no
changes to `LookupResult`, `result::Point`, existing `Error` or the old reverse
methods. Public structs/enums derive Clone, Debug, PartialEq and Serialize;
wire input goes through `parse_point`, not direct serde deserialization that
could bypass validation. `CoordError` also implements std::error::Error/Display.
All fields shown are public. Units are degrees and metres.

```rust
pub struct Geodetic {
    pub lat: f64, pub lon: f64, pub height: Option<f64>,
    pub height_datum: Option<String>, pub geoid_separation: Option<f64>,
}
pub struct Ecef { pub x: f64, pub y: f64, pub z: f64 }
pub enum Origin { Geodetic(Geodetic), Ecef(Ecef) }
pub enum Hemisphere { North, South }
pub enum CellId { Text(String), Integer(u64) }
pub struct Utm {
    pub zone: u8, pub hemisphere: Option<Hemisphere>, pub band: Option<char>,
    pub easting: f64, pub northing: f64,
}
pub enum Frame {
    Geodetic(Geodetic), Ecef(Ecef),
    Enu { e: f64, n: f64, u: f64, origin: Origin },
    Ned { n: f64, e: f64, d: f64, origin: Origin },
    Utm(Utm), Mgrs(String), Geohash(String),
    Pluscode { value: String, reference: Option<Geodetic> },
    H3(CellId), S2(CellId), Dms(String), Nmea(String),
    GeoJson(Vec<f64>), Wkt(String),
}
impl Frame { pub fn label(&self) -> &'static str; }
#[derive(Default)]
pub struct Uncertainty {
    pub accuracy_m: Option<f64>, pub hdop: Option<f64>, pub vdop: Option<f64>,
}
pub struct Point { pub frame: Frame, pub uncertainty: Uncertainty }
pub struct Height {
    pub value_m: f64, pub datum: String, pub geoid_separation_m: Option<f64>,
}
pub struct CellExtent {
    pub boundary: Vec<crate::result::Point>,
    pub half_lat_deg: Option<f64>, pub half_lon_deg: Option<f64>,
    pub grid_size_m: Option<f64>, pub radius_m: f64,
}
pub struct NmeaFix {
    pub talker: String, pub sentence: String, pub utc: Option<String>,
    pub quality: Option<u8>, pub satellites: Option<u8>,
}
pub struct NormalizedPoint {
    pub point: Geodetic, pub input_frame: String, pub origin: Option<Origin>,
    pub conversion: Vec<String>, pub source_height: Option<Height>,
    pub uncertainty: Uncertainty, pub cell_extent: Option<CellExtent>,
    pub nmea: Option<NmeaFix>, pub h3_cell: Option<String>,
}
pub enum CoordError {
    UnsupportedFrame { frame: String },
    MissingField { field: String },
    InvalidType { field: String },
    NonFinite { field: String },
    OutOfRange { field: String },
    ConflictingFields { fields: Vec<String> },
    MissingOrigin,
    MissingReference,
    MissingEllipsoidalHeight,
    UndefinedPosition,
    NoConvergence,
    InvalidSyntax { frame: String },
    InvalidChecksum,
    NoFix,
    UnsupportedCellResolution { frame: String, resolution: u8 },
}
impl CoordError { pub fn code(&self) -> &'static str; }
pub struct CoordIssue { pub code: String, pub message: String }
pub struct QueryMetadata {
    pub input_frame: String, pub declared_frame: Option<String>,
    pub normalized: Option<Geodetic>, pub origin: Option<Origin>,
    pub conversion: Vec<String>, pub source_height: Option<Height>,
    pub uncertainty: Uncertainty, pub cell_extent: Option<CellExtent>,
    pub nmea: Option<NmeaFix>, pub error: Option<CoordIssue>,
}
pub struct PointResult {
    // #[serde(flatten)]
    pub result: crate::result::LookupResult,
    pub query: QueryMetadata,
}
pub fn parse_point(value: &serde_json::Value) -> Result<Point, CoordError>;
pub fn normalize(point: &Point) -> Result<NormalizedPoint, CoordError>;
pub fn geodetic_to_ecef(point: &Geodetic) -> Result<Ecef, CoordError>;
pub fn ecef_to_geodetic(point: &Ecef) -> Result<Geodetic, CoordError>;
pub fn enu_to_ecef(e: f64, n: f64, u: f64, origin: &Origin)
    -> Result<Ecef, CoordError>;
pub fn ecef_to_enu(point: &Ecef, origin: &Origin)
    -> Result<[f64; 3], CoordError>; // [east,north,up]
pub fn utm_to_geodetic(point: &Utm) -> Result<Geodetic, CoordError>;
pub fn geodetic_to_utm(point: &Geodetic, zone: Option<u8>) -> Result<Utm, CoordError>;
pub fn reverse_point(pack: &crate::format::Pack, point: &Point, evidence: bool)
    -> crate::Result<PointResult>;
pub fn reverse_value(pack: &crate::format::Pack, value: &serde_json::Value, evidence: bool)
    -> crate::Result<PointResult>;
pub fn invalid_result(declared_frame: Option<&str>, error: &CoordError) -> PointResult;
```

`Result<T, CoordError>` above is std::result::Result. `geodetic_to_ecef` requires
known ellipsoidal height (or a supplied MSL separation), unlike a 2D reverse
lookup; only origin conversion explicitly supplies absent height zero.
`normalize` revalidates typed values as well as parsed values. It always outputs
`point.height_datum="ellipsoid"` when height is known, otherwise no height/datum;
retained nonellipsoidal height lives in `source_height`. No geoid model is loaded.
Both reverse helpers map CoordError into ordinary `invalid_input`, an actionable
`hint` and `query.error`, never into `Error::Input`/pack corruption. Data errors
still propagate via `crate::Result`. `reverse_value` preserves the declared label
and calls the same normalizer; direct typed calls have `declared_frame=None`.
H3 `h3_cell` dispatches to `Pack::from_h3`; all other normalized points use
`Pack::reverse`. Geohash/OLC/MGRS/S2 therefore return centre context, not a
consensus over their footprint. `invalid_result` has no normalized point and
empty conversion/uncertainty; do not echo malformed or nonfinite values.

Wire object keys are `{frame, ...components, uncertainty?}`. `frame` defaults to
`geodetic`; geodetic components are `lat,lon,height?,height_datum?,geoid_separation?`;
ECEF `x,y,z`; ENU `e,n,u,origin`; NED `n,e,d,origin`; UTM the fields above with
`hemisphere:"N"|"S"`; text frames `value`; H3/S2 `cell`; GeoJSON
`coordinates:[lon,lat,height?]`, optionally `type:"Point"`. Origin is a nested
frame object limited to geodetic/ECEF. Pluscode optionally includes `reference`
as a geodetic component object. `uncertainty` has only the three numeric keys
above; all must be finite and nonnegative, with no implied confidence level.
Unknown keys, booleans/strings in numeric fields and conflicting components fail
validation. Numeric JSON integers are allowed for coordinates. Missing optional
values and null are equivalent; required null is invalid. Frame labels are
lower-case, aliases normalize, arbitrary CRS labels produce UnsupportedFrame.

Wire serialization of Frame/Origin is the same tagged component object; Point
flattens Frame and adds uncertainty. All metadata Options serialize as null and
conversion arrays as arrays **inside the new `query` object**. Empty uncertainty
has its three null members. Existing result omission rules stay as before.
For cell identifiers, strings are canonical H3 hex or S2 hex tokens (S2 token
right-padded to 16 hex digits before decoding); integral u64 is accepted by
Rust/Python. Node accepts string or bigint and converts bigint losslessly to
the appropriate hex string; Number cell identifiers are refused. No inference
between decimal strings and hex tokens. Origin recursion is forbidden.

Conversion IDs are ordered, stable strings: `geodetic_identity`,
`ecef_to_geodetic_wgs84`, `enu_to_ecef_wgs84`, `ned_to_enu`,
`origin_geodetic_to_ecef_wgs84`, `origin_height_assumed_zero`,
`utm_inverse_wgs84_kruger6`, `mgrs_cell_center_wgs84`,
`ups_inverse_wgs84`, `geohash_cell_center`, `pluscode_recover_short`,
`pluscode_cell_center`, `h3_stored_ancestor`, `s2_cell_center`, `dms_parse`,
`nmea_checksum_parse`, `msl_plus_separation`, `geojson_lon_lat`, `wkt_lon_lat`.
Record only operations performed, in order. Preserve original local origin and
supplied height metadata. Input `accuracy_m` and VDOP pass through; GGA HDOP is
used if caller HDOP is absent, and conflicting supplied HDOP is a field conflict.
CellExtent is decoded precision, separate from user measurement accuracy and
`distance_band`. Boundaries are unclosed ordered lon/lat points as named objects;
geohash/OLC half-sizes are exact angular half-spans. MGRS grid_size_m is
`10^(5-digit_pairs)`; its boundary is the transformed four grid corners.
`radius_m` is maximum centre-to-listed-vertex great-circle distance using
R=6371008.8 m, labelled in documentation as a spherical footprint summary,
not a confidence radius or guaranteed curved-edge bound. Dateline edges use
wrapped longitude differences. Never turn HDOP into metres without a receiver
error model; never combine the several uncertainties statistically.

## Client additions

Python defines `Frame` literals, discriminated TypedDict `Point` inputs and
`Origin` in `thereabouts.coords` (separate from `results.Point`). Add:

```python
Geocoder.reverse_point(self, point: Point, *, evidence: bool = False) -> Result
Geocoder.reverse_points(self, points: Iterable[Point], *, evidence: bool = False) -> Iterator[Result]
Geocoder.reverse_frame_columns(self, columns: Mapping[str, NDArray[Any]], *,
    frame: Frame = "geodetic", origin: Origin | None = None) -> dict[str, NDArray[Any]]
```

`reverse_frame_columns` initially supports numeric geodetic/ECEF/ENU/NED columns,
with equal-length 1D nonboolean numeric arrays and an optional common origin.
Required columns use canonical component names; optional geodetic height and
accuracy_m/hdop/vdop are numeric columns. A `height` column is ellipsoidal;
other datums and heterogeneous origins use `reverse_points`. Other frame values
raise ValueError with that guidance. Preserve strides by copying before GIL
release, then normalize/lookup in one Rust loop. Return existing numeric/dictionary
columns plus a length-N object array `query` of frozen QueryMetadata dataclasses;
do not change old reverse_columns or silently discard provenance. Build no JSON
strings per numeric row. Scalar/stream input-domain failures return Result with
query.error; invalid API shapes (e.g. a bare tuple) are TypeError. Lifecycle and
data errors stay exceptions, including suspended iterators after close.

PyO3 adds `reverse_point(point_json: str, *, evidence=False) -> dict`, with the
same signature in `_core.pyi`, and a native `reverse_frame_columns(columns,
*, frame="geodetic", origin_json=None) -> dict` taking numeric arrays. Python
validates JSON-representable scalar types, rejects bool/np.bool_, converts NumPy
scalars, and invokes the shared parser; malformed numeric values must become
invalid_input rather than a json.dumps exception or silent NaN-to-null success.
Use a bounded invalid object sentinel in the offending numeric field where JSON
cannot represent a value; the Rust parser returns InvalidType. Do not use null
for an optional numeric field, which would silently erase it. Typed Rust f64
calls instead produce NonFinite. No Python conversion maths.
New result encoding combines the existing manual `result::encode` output with
query serialization. Append `query: QueryMetadata | None = None` to Python
Result, freeze nested structures, omit it from to_dict when None. Avoid changing
top-level Python exports: new methods plus `thereabouts.coords` suffice.

Node adds `Frame` and `CoordinatePoint` discriminated unions; keep existing
`Point` for lat/lon results. Add
`reversePoint(point: CoordinatePoint, options?: Options): Promise<Result>` and
`reversePoints(points: Iterable<CoordinatePoint> | AsyncIterable<CoordinatePoint>,
options?: Options): AsyncIterable<Result>`. `Result.query?: QueryMetadata` is
deeply frozen. New WASM method `reversePoint(request: &str, evidence: bool)
-> Result<String, JsValue>` calls `coords::reverse_value`; malformed request JSON
becomes a coordinate invalid result, not corrupt_pack. JS validates object
shape, numbers and bigints before serialization (JSON.stringify would turn
NaN/Infinity into null); use the same invalid numeric sentinel as Python, with
no rounding through Number and no duplicate geodesy logic.
No new module-level shortcut is necessary. Streaming preserves backpressure.

MCP keeps existing reverse/h3 schemas and adds read-only `reverse_point(point,
evidence=False) -> dict`. Describe the discriminated Point schema with strict
numeric types (no bool/string coercion), forbid unknown component keys, expose
origin and uncertainty, and delegate to Python. Transport/schema mistakes remain
MCP validation errors; in-domain invalid coordinates produce normal public
invalid_input JSON. Data errors remain ToolError with their existing codes.
MCP does not expose file paths, ingestion jobs, installation or network access.

Examples (the ECEF example is the WGS84 equator/Greenwich intersection):

```python
geo.reverse_point({"frame": "ecef", "x": 6378137, "y": 0, "z": 0})
geo.reverse_point({"frame": "enu", "e": 10, "n": 0, "u": 0,
                   "origin": {"frame": "geodetic", "lat": 48.8566, "lon": 2.3522}})
geo.reverse_point({"frame": "geodetic", "lat": 48.8566, "lon": 2.3522,
                   "uncertainty": {"accuracy_m": 4, "hdop": 0.9}})
```

## CLI, CSV, NDJSON and satnav streams

Update both shared grammar/validation and native clap dispatch; Python's CLI
shim stays a shim. Node's CLI routes to the same Rust implementation. Add:

| Input | Scalar flags | CSV defaults and overrides |
| --- | --- | --- |
| Geodetic | Existing --lat/--lon; opt-in --frame geodetic; --height, --height-datum, --geoid-separation | Existing aliases for lat/lon unchanged; --height-col, --height-datum-col, --geoid-separation-col |
| ECEF | --frame ecef --x --y --z | Exact x,y,z or --x-col/--y-col/--z-col |
| ENU/NED | --frame enu/ned --x --y --z --origin JSON | x/y/z flags map to e/n/u or n/e/d, respectively; automatic headers e,n,u or n,e,d; overrides --x-col/--y-col/--z-col |
| UTM | --frame utm --zone --hemisphere (or --band) --easting --northing | Exact matching names or --zone-col/--hemisphere-col/--band-col/--easting-col/--northing-col |
| Text/H3/S2 | --frame LABEL --value TEXT; short OLC also --reference JSON | value (H3/S2: cell) or --value-col |
| Any frame | --point JSON (complete typed object) | Nested/heterogeneous input uses NDJSON |

Common scalar/frame-wide flags: --accuracy-m, --hdop, --vdop, --origin JSON,
--reference JSON. CSV has --accuracy-col, --hdop-col, --vdop-col. Metadata flags
require explicit --frame or --point; absent flags never start a new result mode.
Optional CSV metadata columns activate only in explicit frame mode, use exact
names height,height_datum,geoid_separation,accuracy_m,hdop,vdop, and are optional
unless an override names a missing header. Required headers have exactly one
match; two dimensions cannot bind the same column. UTM zone/hemisphere/band
may be supplied as uniform scalar options or row columns, never both. Origin
and OLC reference in CSV are uniform flags; per-row values belong in NDJSON.
There is no mixed-frame CSV or --frame-col in this increment. GeoJSON arrays
use --point or NDJSON; --frame geojson with CSV is a usage error with that
guidance. WKT remains a text value and works with single-column frame-mode CSV.

FILE, --point, scalar components are mutually exclusive. --point contains its
frame and metadata and cannot be mixed with component/metadata/--frame flags.
--frame is required for x/y/z or text flags; never interpret --lat as x. Reject
irrelevant flags, unknown frame, partial dimension sets, malformed origin JSON
and conflicting options before opening data (exit 2). Values failing geographic
validation produce invalid_input result JSON and scalar exit 2. Origin absence
is usage error in uniform CLI syntax, row invalid_input in NDJSON.

CSV without --frame keeps the exact old schema/recognition rules. Frame mode
permits single-column geocode CSV; old single-column CSV remains a usage error.
Preserve all raw input fields/header order, quote per RFC 4180, reject duplicate,
empty and thereabouts_-reserved headers, continue after invalid rows in order.
Bad numeric rows, missing row components, invalid codes/checksums and mixed-up
axis fields are invalid_input; a globally missing required header is usage.

NDJSON objects with `frame` opt into new decoding. Without it, retain legacy
numeric lat/lon behavior unless --frame sets a uniform default. A row-declared
frame conflicting with --frame is invalid_input (aliases compare canonically);
it never silently overrides. --origin/--reference supply missing row context;
if both are supplied, require equal normalized context or reject the row.
All column flags remain CSV-only. Pass arbitrary record fields through, but
extract only recognized components for Rust parsing; extra coordinate-component
keys inconsistent with the declared frame are errors in frame mode. A record
with no frame remains legacy even if it has unrelated extra columns.

New structured result order appends `query` after existing fields. Scalar
frame-mode CSV emits it as compact JSON; tables keep seven summary columns,
with provenance available through --fields query.* or --json. Register query
and all scalar leaves (input_frame, declared_frame, normalized.*, error.*,
uncertainty.*, source_height.*); register origin, conversion, nmea, cell_extent
as containers, plus nmea scalar leaves and cell_extent numeric leaves.
Batch frame-mode CSV reserves nullable thereabouts_query for every row, including
a bad first row. For mixed NDJSON-to-CSV/table, extend the existing bounded spool
prepass to detect whether any row opts in; reserve the column once, using null
for legacy/malformed rows. Pure legacy input must not gain it. Streaming
JSON/NDJSON may omit query on legacy rows. --fields still wins over defaults.
Keep exit 5 for any failed batch row; --strict misses remain exit 1 when no row
failed, normal completion 0, existing missing/corrupt data codes unchanged.

Add `--input-format auto|csv|ndjson|nmea` separately from output --format. Default
auto keeps today's detection. Explicit nmea requires --frame nmea and reads one
sentence per nonblank line, preserves raw sentence as `value`, verifies each,
and continues after errors; no serial device, pairing, clock interpolation or
download. CSV x/y/z and NDJSON point records are native. GPX is not natively read
in this increment: document extracting trkpt lat/lon into NDJSON, retaining ele
with an explicit/unknown height datum, and never claiming GPX ele is ellipsoidal.

## Diagnostics

CoordError codes are the snake_case enum names, except `UnsupportedCellResolution`
uses `unsupported_cell_resolution`. Display text becomes hint/query.error.message;
status is invalid_input, not a new result Status. Pin these key messages in tests:

| Error | Message |
| --- | --- |
| UnsupportedFrame(crs:...) | `Thereabouts does not transform arbitrary CRSs; use GeoReconcile crs: support or pyproj, then pass WGS84 geodetic coordinates` |
| UnsupportedFrame(llv) | `Choose frame enu or ned and supply an origin; llv does not define axis order` |
| MissingOrigin | `Frame enu/ned requires an explicit geodetic or ECEF origin` |
| MissingReference | `Short plus codes require a geodetic reference; use a full plus code otherwise` |
| MissingEllipsoidalHeight | `ECEF conversion requires ellipsoidal height or a supplied geoid separation; no geoid model is applied` |
| UndefinedPosition | `ECEF position or local-frame orientation is undefined; provide a valid position and a geodetic pole origin` |
| NonFinite / OutOfRange | `Coordinate field <field> must be finite` / `Coordinate field <field> is outside the supported range` |
| InvalidChecksum / NoFix | `NMEA checksum is missing or invalid` / `NMEA sentence does not contain an active position fix` |
| UnsupportedCellResolution(h3,r) | `H3 reverse queries support resolutions 0 through 8; use an explicit parent cell` |

Remaining variants use field/frame-specific messages; never expose serde's pack
JSON/corruption mapping for coordinate parsing. Unknown frame guidance lists the
supported labels. Unsupported WKT CRS prefixes point at the same external CRS
remedy. Datum labels are metadata, not instructions to transform vertical CRSs.

## Vectors, sources and tolerances

Store machine-readable vectors in `tests/fixtures/coordinates/vectors.json`,
not a top-level `*-vectors.json` (Node discovers those as legacy pack fixtures).
Each case includes source/derivation, input, expected normalized values or error,
per-field tolerance and footprint semantics. Rust owns the fixture; all clients
consume it without editing it. Source URLs below are reference targets, **not
retrieved during this offline planning pass**. Do not present recalled examples
as independently authenticated publications.

| Vector | Expected / tolerance | Source and verification status |
| --- | --- | --- |
| Equator, Greenwich: lat=0,lon=0,h=0 | ECEF (6378137,0,0), <1e-6 m; east basis +Y, north +Z, up +X | WGS84 constants, checked against installed pyproj |
| North/south pole | z=±6356752.314245179 m, x=y=0 analytically; <1e-6 m; longitude convention tested separately | WGS84, pyproj north-pole check; south by symmetry |
| Dateline lat=0,lon=±180,h=0 | (-6378137,0,0), <1e-6 m; wrapped longitude comparison | WGS84, pyproj +180 check |
| Paris lat=48.8566,lon=2.3522,h=35 | (4200937.804351204,172560.72143257968,4780107.699250484) m; <1 mm | Offline pyproj 3.8.0 / PROJ 9.8.1, EPSG:4979→4978, always_xy; synthetic, not a surveyed station |
| EPSG GN7-2 geographic/geocentric example | lat=53°48′33.82″,lon=2°07′46.38″,h=73; XYZ rounded (3771793.97,140253.34,5124304.35); 0.01 m publication precision | EPSG method 9602 candidate; full precision independently reproduced offline, publication/edition still to verify |
| GEO height 35,786,000 m at (0,0) | (42164137,0,0); <1 mm round-trip | Analytic and offline pyproj |
| ENU (10,20,30) at (0,0,0) | ECEF (6378167,10,20); NED (20,10,-30) same | Analytic basis; exact arithmetic before inverse tolerance |
| UTM 31N at lon=3,lat=0 | E=500000,N=0; <1 mm | Offline pyproj EPSG:32631 |
| Paris UTM 31N | E=452482.5327026278,N=5411717.176868899; <1 mm | Offline pyproj EPSG:32631 |
| Sydney lat=-33.8688,lon=151.2093, UTM 56S | E=334368.633648097,N=6250948.345385009; <1 mm | Offline pyproj EPSG:32756 |
| MGRS `31UDQ4825111932` | 1 m square centred at UTM (448251.5,5411932.5); centre-to-corner distinction | MGRS lettering arithmetic; published example verification pending, do not claim oracle checked |
| Geohash `u4pruydqqvj` | centre lat=57.64911063015461,lon=10.407439693808556; half-spans 0.0000006705522537231445° each | Bit-interleaving vector; implement independent bit-interval test, <1e-12° |
| OLC `849VCWC8+Q9` | centre lat=37.4219375,lon=-122.0840625; half-spans 0.0000625° | OLC arithmetic, <1e-10°; short `CWC8+Q9` + reference (37.42,-122.08) recovers it |
| DMS `48°51′24.1″N 2°21′07.9″E` | lat=48.85669444444444,lon=2.352194444444444; <1e-12° | Arithmetic from shared vocabulary |
| `$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47` | lat=48.1173,lon=11.516666666666667,h=592.3,MSL=545.4,sep=46.9,HDOP=.9,quality=1,sats=8 | Common GGA reference candidate; verify checksum in fixture and compare arithmetic (<1e-10° / 1e-9 m), source publication not fetched |
| GeoJSON [2.3522,48.8566,35], WKT POINT Z equivalent | same geodetic triple; exact parsed f64 | RFC 7946 / Simple Features axis ordering |
| H3 `881fb46625fffff`, r0, pentagon, r8, r9 | centre/boundary from cached h3o; r9 invalid; new r≤8 result minus query equals old from_h3 | Existing Thereabouts fixtures and h3o 0.9.5 |
| S2 tokens `1`,`3`,`5`,`7`,`9`,`b` | six face centres at axes; level 0; reject zero/invalid sentinel/face | S2 cell encoding; local s2sphere available for independent vectors |

Published references to attach precisely in implementation fixtures:
[NGA WGS84](https://earth-info.nga.mil/index.php?dir=wgs84&action=wgs84),
[EPSG guidance notes](https://epsg.org/guidance-notes.html) (GN7-2, method 9602),
[Karney transverse Mercator](https://doi.org/10.1007/s00190-011-0445-3),
[GeographicLib MGRS](https://geographiclib.sourceforge.io/C++/doc/classGeographicLib_1_1MGRS.html),
[Open Location Code](https://github.com/google/open-location-code),
[S2 cell hierarchy](https://s2geometry.io/devguide/s2cell_hierarchy.html),
[RFC 7946 §3.1.1](https://www.rfc-editor.org/rfc/rfc7946#section-3.1.1),
[OGC Simple Features](https://www.ogc.org/standards/sfa/).
Record exact upstream test names/editions when available offline; no downloads
are authorized. A published surveyed-station ECEF fixture with datum realization
and epoch remains a release evidence item; the EPSG worked example/Paris are
not substitutes for claiming a surveyed station was checked.

Add seeded property tests: geodetic→ECEF→geodetic→ECEF residual <1 mm (height
<1 mm, angles <1e-8° away from poles), both longitude endpoints, near poles,
negative and satellite heights; rotate ENU/NED at random origins; UTM zone edges,
Norway/Svalbard, southern bands and ±80/84 cutoffs; MGRS precisions 0–5 and UPS
both poles; OLC padded/short/grid codes; geohash dateline/poles; S2 levels 0–30;
NMEA GN/GP GGA/RMC/GLL valid/void/bad checksum, missing separation, invalid units,
DMS sign conflict; swapped WKT/GeoJSON order and invalid dimensionality; bool,
null, NaN/Inf, unknown frames, missing/conflicting origins, invalid uncertainty.
Different native/WASM transcendental arithmetic needs numeric tolerances, never
relaxed status/cell/error/schema equality. Use non-boundary normalized points
for exact lookup-cell equality and test boundary admission separately.

## Implementation risks, gates and documentation

Pure conversions are independent of Pack/IO and allocate only small outputs;
normalization must never read data. Cache rotation per uniform batch origin,
decode each point once, bound parsers, avoid regex backtracking and whole-stream
buffers. Benchmark 10k synthetic points against scalar/column baselines, one
process at a time; record elapsed/RSS, no new performance promises.

Measure stripped WASM and gzipped WASM before/after plus installed Node payload;
record absolute/delta bytes. Order-n^6 UTM/UPS and S2 correctness is the highest
math risk. Add no crates, network/grid resources, JS geodesy package or optional
feature matrix. Node build must honour the preset CARGO_TARGET_DIR instead of
its current hard-coded core/target. Node 23 here is not the Node 22/24 CI matrix.
PyO3 is 0.26, abi3-py311; update `_core.pyi` and both manual and JSON result paths
together, retain detached ownership and NumPy dtype rejection. The CLI must
reserve query columns before first output, including invalid first rows.

Rust 1.99 gates: from core/, `cargo fmt --check`, offline/locked clippy with
`--all-targets --all-features -- -D warnings`, tests for touched crates, and
wasm32 cargo check. Python uses a local editable maturin build then targeted
pytest, ruff and mypy; Node uses installed wasm-bindgen 0.2.129, an offline WASM
build, tests, typecheck and format. Full workflow tests include pipeline tests
and installation/publication jobs and are outside this task's authorization.
Keep both workflow files unchanged; missing offline tooling is a reported gate
blocker, not a reason to skip with success or weaken CI. Commands and precise
ownership are in the package briefs and exploration notes.

Write/update: Python and Node READMEs, a user-facing coordinate-input guide,
CLI grammar/help and docs/clients/cli.md (including metadata field selection and
NMEA logs), MCP schema descriptions, docs index/README links, release.md editable
offline build recipe, and status.md with actual validation/size results. Explain
LLV axis choice, origin requirements, height datums, geocode representative
centres, H3 resolution limits, GPX preprocessing, explicit axis ordering and
the GeoReconcile/pyproj boundary. Do not document unverified gates as passed.

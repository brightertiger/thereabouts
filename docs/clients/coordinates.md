# Explicit coordinate frames

Use `Geocoder.reverse_point` in Python, `Geocoder.reversePoint` in Node, or MCP's
read-only `reverse_point` tool for framed input. One Rust parser and normalizer
own conversions and domain validation. These additions require the corresponding
core and client build; see [qualification](status.md) for the integration state.

Existing named WGS84 `reverse`, H3 lookup, streams and NumPy columns retain their
signatures and output. New input types live in `thereabouts.coords` and Node's
`CoordinatePoint`; the old result `Point` remains latitude and longitude.
There is no tuple/triple or identifier guessing. Omitted `frame` means geodetic.

```python
from thereabouts import Geocoder
from thereabouts.coords import Point

with Geocoder(data_dir="./store") as geo:
    point: Point = {"frame": "ecef", "x": 6378137, "y": 0, "z": 0}
    result = geo.reverse_point(point)  # WGS84 equator at Greenwich
    print(result.query.normalized)
    local = geo.reverse_point({
        "frame": "enu", "e": 10, "n": 0, "u": 0,
        "origin": {"frame": "geodetic", "lat": 48.8566, "lon": 2.3522},
    })
    print(local.query.origin, local.query.conversion)
```

```js
const result = await geo.reversePoint({
  frame: "geodetic", lat: 48.8566, lon: 2.3522,
  uncertainty: { accuracy_m: 4, hdop: 0.9 },
});
console.log(result.query.normalized, result.query.uncertainty);
for await (const item of geo.reversePoints([
  { frame: "h3", cell: 0x881fb46625fffffn },
  { frame: "geojson", coordinates: [2.3522, 48.8566] },
])) console.log(item.query);
```

## Inputs

Wire objects contain `frame`, its components, and optional `uncertainty`.
Unknown fields and mixed component sets fail validation. All positions use
WGS84; angles are degrees, lengths are metres. Numbers must be finite and
numeric, without boolean/string coercion. Missing and null optional members
are equivalent; a required null member is invalid.

| Frame | Components | Interpretation |
| --- | --- | --- |
| `geodetic` | `lat`, `lon`, optional `height`, `height_datum`, `geoid_separation` | WGS84; `latlon`, `lla`, `llh` canonicalize to `geodetic` |
| `ecef` | `x`, `y`, `z` | Earth-centred, Earth-fixed Cartesian metres |
| `enu` | `e`, `n`, `u`, `origin` | East, north, up at the explicit origin |
| `ned` | `n`, `e`, `d`, `origin` | North, east, down at the explicit origin |
| `utm` | `zone`, `hemisphere` (`N`/`S`) or `band`, `easting`, `northing` | WGS84 UTM, zones 1–60 |
| `mgrs` | `value` | WGS84 UTM/UPS MGRS, centre of the encoded grid square |
| `geohash` | `value` | Cell centre; decoded angular half-spans |
| `pluscode` | `value`, optional `reference` | Full Open Location Code; short code requires geodetic reference components |
| `h3` | `cell` | Input H3 centre and existing stored-ancestor lookup, r0–r8 only |
| `s2` | `cell` | S2 cell centre; hex tokens are right-padded to 16 digits for decoding |
| `dms` | `value` | Latitude then longitude, with N/S and E/W; for example `48 51 24.1 N, 2 21 7.9 E` |
| `nmea` | `value` | One checksummed GP/GN GGA, RMC or GLL sentence with an active fix |
| `geojson` | `coordinates: [lon, lat, height?]`, optional `type: "Point"` | Point coordinates only; no Feature/collection |
| `wkt` | `value` | `POINT (lon lat)` or `POINT Z (lon lat height)` |

H3/S2 accept hex strings or Python integer/Rust u64 identifiers. Node accepts
strings or bigint and converts bigint losslessly to the appropriate hex string;
JavaScript Number cell IDs are refused, even if they look integral. Decimal
strings are never inferred to be integer IDs. H3 r9–r15 require an explicitly
chosen parent; a coarse H3 query is never replaced by an r8 descendant.
Other geocodes query their decoded centre, without promising unanimous context
across the footprint.

## LLV and origins

“LLV” does not establish an axis order: choose `enu` or `ned` and supply an
origin. Origin is a nested geodetic or ECEF object, with no recursive origin.
A geodetic origin without height explicitly assumes ellipsoidal zero and records
`origin_height_assumed_zero`. A supplied nonellipsoidal origin height needs a
known ellipsoidal equivalent. At a pole, use a geodetic origin with explicit
longitude to orient east/north; a polar ECEF origin supplies no azimuth.
These are Cartesian tangent frames, including for large offsets, rather than
flat surface-distance approximations. ECI, velocity, attitude and epochs are
outside this API.

## Heights and uncertainty

Known normalized heights are ellipsoidal. No geoid grid is loaded. MSL altitude
plus a supplied geoid separation yields ellipsoidal height and records
`msl_plus_separation`. Other or unknown height datums remain in `source_height`;
`normalized.height` and its datum stay null. Datum labels do not request a
vertical CRS transformation. Direct Rust geodetic-to-ECEF conversion requires
known ellipsoidal height; the explicit zero-height assumption applies only to
an absent origin height.

`uncertainty` contains `accuracy_m`, `hdop`, and `vdop`, all optional,
finite and nonnegative. HDOP and VDOP are dimensionless. No confidence level,
conversion of DOP to metres, statistical combination or receiver error model
is implied. GGA HDOP is retained when caller HDOP is absent; a conflicting
caller value is rejected. NMEA GGA also preserves UTC, quality, satellites,
MSL height and supplied separation.

`cell_extent` describes decoded precision separately from measured uncertainty
and the lookup's `distance_band`. Its boundary is an unclosed sequence of named
lat/lon vertices. Geohash/plus-code half-spans are angular; MGRS `grid_size_m`
is the encoded grid spacing. `radius_m` is a spherical footprint summary: the
maximum centre-to-listed-vertex great-circle distance using R=6371008.8 m and
wrapped longitude differences. It is neither a confidence radius nor a
guaranteed curved-edge bound.

## Results, batches and errors

`result.point` stays the H3 query-cell centre; `city.point` stays a catalogue
anchor. Only the new `query.normalized` describes the normalized exact input or
representative decoded centre. `query` is present without `evidence=True` and
includes declared/canonical frame, origin, ordered conversion IDs, source
height, uncertainty, decoded extent, NMEA metadata and a coordinate error.
All optional query members serialize as null; empty uncertainty has three null
members. Old `Result.to_dict()` omits `query` entirely. Python query dataclasses,
their nested structures, and Node query objects are immutable and detached.

Python `reverse_points(points, *, evidence=False)` and Node
`reversePoints(points, options)` consume one point at a time in order. Node
also accepts async iterables and preserves backpressure. Queries and suspended
iterators fail after close; already returned results remain usable.

Python `reverse_frame_columns(columns, *, frame="geodetic", origin=None)` accepts
equal-length 1D NumPy numeric arrays for geodetic/ECEF/ENU/NED (including geodetic
aliases). Boolean and object dtypes are rejected. Required names match the
components above; optional columns are geodetic `height`, `accuracy_m`, `hdop`,
`vdop`. Height columns are ellipsoidal. A common origin is supported for local
frames. Use `reverse_points` for other frames, other datums or varying origins.
Rust copies strided arrays before releasing the GIL and normalizes/looks up in
one loop, without row JSON strings. Output retains dictionary columns and null
masks and adds a length-N object array of frozen `QueryMetadata` instances.
Empty arrays are supported. The old `reverse_columns` output is unchanged.

```python
import numpy as np

columns = geo.reverse_frame_columns({
    "lat": np.array([48.8566, 50.8503]),
    "lon": np.array([2.3522, 4.3517]),
    "hdop": np.array([0.9, 1.2]),
})
print(columns["query"][0].normalized)
```

Coordinate-domain failures return the normal `invalid_input` status, an
explanatory `hint` and `query.error`; malformed values are not echoed. JSON
adapters represent nonfinite numeric fields with a bounded invalid object, so
the Rust parser returns `invalid_type` without erasing optional values. Typed
Rust numeric calls, including numeric columns, instead report `non_finite`.
Bare tuples/nonobject API inputs raise TypeError; column shape errors raise
TypeError/ValueError. Existing data and lifecycle exceptions keep their codes.

### MCP schema

MCP adds read-only `reverse_point(point, evidence=False)`. Its strict,
discriminated schema rejects transport type/shape mistakes, unknown keys and
numeric coercion; valid shapes with out-of-domain coordinates return ordinary
`invalid_input` JSON. Data/lifecycle failures remain coded ToolError. Existing
MCP reverse/h3 schemas are unchanged. It exposes no installation, ingestion,
file paths or network tools.

The tool input has exactly `point` (required object) and `evidence` (optional
boolean, default false). `point.frame` selects the variants in the frame table
above; omission defaults to geodetic, and `latlon`, `lla`, `llh` are aliases.
Geodetic accepts named `lat`/`lon`; ECEF takes `x`/`y`/`z`; ENU and NED take
their named axes plus a geodetic/ECEF `origin`. UTM takes integer `zone`,
`easting`, `northing`, and optional `hemisphere`/`band`. Text frames take `value`;
pluscode also accepts a geodetic `reference`. H3/S2 take a string or integer
`cell`. GeoJSON takes a two- or three-number `coordinates` array and optional
`type: "Point"`. Every variant accepts optional `uncertainty` with
`accuracy_m`, `hdop`, `vdop`. Numeric fields accept JSON numbers, never booleans
or numeric strings; component/origin/uncertainty objects forbid unknown keys.
Optional metadata may be null. Domain errors such as latitude 91 remain result
JSON with `query.error`; malformed transport shapes are tool validation errors.

## Files and the GeoReconcile boundary

These library APIs accept points/iterables, not file paths. Preprocess GPX with
an XML reader in your application: extract each `trkpt`/`wpt`'s named latitude
and longitude, and preserve the documented source elevation datum when known.
Do not assume an unlabelled GPX elevation is ellipsoidal. Convert GeoJSON
Feature/FeatureCollection wrappers to individual Point objects; split NMEA logs
into explicitly labelled sentence objects. For CSV, select named numeric columns
or create framed objects. Track fusion and file ingestion are not lookup policy.
See the separately maintained [CLI guide](cli.md) for command input modes.

Arbitrary `crs:` labels and WKT CRS prefixes are refused. Use GeoReconcile's
`crs:` support or pyproj externally, then pass explicit WGS84 geodetic values.
Thereabouts does no conflation or covariance modelling and changes no data,
packs, lookup resolution, ranking or coverage policy for these inputs.

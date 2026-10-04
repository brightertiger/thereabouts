//! Public version-one coordinate contract. Inputs are validated by `parse_point`/`normalize`.
use serde::Serialize;

/// WGS84 latitude/longitude in degrees and optional source height in metres.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Geodetic {
    /// Latitude in degrees.
    pub lat: f64,
    /// Longitude in degrees.
    pub lon: f64,
    /// Source height in metres; absence does not imply zero.
    pub height: Option<f64>,
    /// Height datum label; omitted with a height means ellipsoid.
    pub height_datum: Option<String>,
    /// Supplied geoid separation in metres, never inferred from a model.
    pub geoid_separation: Option<f64>,
}
/// WGS84 Earth-centred Earth-fixed metres.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Ecef {
    /// X toward the equator/Greenwich.
    pub x: f64,
    /// Y toward the equator/90° east.
    pub y: f64,
    /// Z toward the north pole.
    pub z: f64,
}
/// Explicit local-frame origin; a geodetic pole retains its supplied longitude.
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "frame", rename_all = "lowercase")]
pub enum Origin {
    /// Geodetic origin, with zero height assumed only when absent.
    Geodetic(Geodetic),
    /// ECEF origin; an exact pole has no defined tangent azimuth.
    Ecef(Ecef),
}
/// Hemisphere for UTM false northing.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub enum Hemisphere {
    /// Northern hemisphere.
    #[serde(rename = "N")]
    North,
    /// Southern hemisphere.
    #[serde(rename = "S")]
    South,
}
/// Explicit hexadecimal token or lossless integer identifier.
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(untagged)]
pub enum CellId {
    /// H3 hexadecimal cell or S2 hexadecimal token (right padded).
    Text(String),
    /// Exact unsigned 64-bit cell identifier.
    Integer(u64),
}
/// WGS84 UTM metres, with a hemisphere or latitude band (or both).
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Utm {
    /// Zone 1 through 60.
    pub zone: u8,
    /// Hemisphere, when specified.
    pub hemisphere: Option<Hemisphere>,
    /// Latitude band C–X, excluding I and O.
    pub band: Option<char>,
    /// Easting in metres.
    pub easting: f64,
    /// Northing in metres, including southern false northing.
    pub northing: f64,
}
/// Explicit native frame; no inference from tuples or identifier strings.
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "frame", rename_all = "lowercase")]
pub enum Frame {
    /// Named WGS84 geographic input.
    Geodetic(Geodetic),
    /// WGS84 Cartesian input.
    Ecef(Ecef),
    /// East/north/up metres in a Cartesian tangent frame.
    Enu {
        /// East.
        e: f64,
        /// North.
        n: f64,
        /// Up.
        u: f64,
        /// Explicit origin.
        origin: Origin,
    },
    /// North/east/down metres in a Cartesian tangent frame.
    Ned {
        /// North.
        n: f64,
        /// East.
        e: f64,
        /// Down.
        d: f64,
        /// Explicit origin.
        origin: Origin,
    },
    /// WGS84 UTM.
    Utm(Utm),
    /// UTM or UPS MGRS cell.
    #[serde(serialize_with = "serialize_text")]
    Mgrs(String),
    /// Base-32 geohash cell.
    #[serde(serialize_with = "serialize_text")]
    Geohash(String),
    /// Open Location Code, short only with a reference.
    Pluscode {
        /// Code text.
        value: String,
        /// Explicit reference for recovery.
        reference: Option<Geodetic>,
    },
    /// Stored H3 query cell, resolution 0 through 8.
    #[serde(serialize_with = "serialize_cell")]
    H3(CellId),
    /// S2 cell, level 0 through 30.
    #[serde(serialize_with = "serialize_cell")]
    S2(CellId),
    /// Latitude then longitude sexagesimal text with hemispheres.
    #[serde(serialize_with = "serialize_text")]
    Dms(String),
    /// One checksummed active GP/GN GGA/RMC/GLL sentence.
    #[serde(serialize_with = "serialize_text")]
    Nmea(String),
    /// Point coordinates in longitude/latitude/optional height order.
    #[serde(rename = "geojson", serialize_with = "serialize_coordinates")]
    GeoJson(Vec<f64>),
    /// POINT or POINT Z geometry.
    #[serde(serialize_with = "serialize_text")]
    Wkt(String),
}
fn serialize_text<S: serde::Serializer>(value: &str, s: S) -> Result<S::Ok, S::Error> {
    use serde::ser::SerializeMap;
    let mut map = s.serialize_map(Some(1))?;
    map.serialize_entry("value", value)?;
    map.end()
}
fn serialize_cell<S: serde::Serializer>(value: &CellId, s: S) -> Result<S::Ok, S::Error> {
    use serde::ser::SerializeMap;
    let mut map = s.serialize_map(Some(1))?;
    map.serialize_entry("cell", value)?;
    map.end()
}
fn serialize_coordinates<S: serde::Serializer>(value: &[f64], s: S) -> Result<S::Ok, S::Error> {
    use serde::ser::SerializeMap;
    let mut map = s.serialize_map(Some(1))?;
    map.serialize_entry("coordinates", value)?;
    map.end()
}
impl Frame {
    /// Canonical vocabulary label, including canonicalized geographic aliases.
    #[must_use]
    pub const fn label(&self) -> &'static str {
        match self {
            Self::Geodetic(_) => "geodetic",
            Self::Ecef(_) => "ecef",
            Self::Enu { .. } => "enu",
            Self::Ned { .. } => "ned",
            Self::Utm(_) => "utm",
            Self::Mgrs(_) => "mgrs",
            Self::Geohash(_) => "geohash",
            Self::Pluscode { .. } => "pluscode",
            Self::H3(_) => "h3",
            Self::S2(_) => "s2",
            Self::Dms(_) => "dms",
            Self::Nmea(_) => "nmea",
            Self::GeoJson(_) => "geojson",
            Self::Wkt(_) => "wkt",
        }
    }
}
/// Measurement metadata, without implied confidence or statistical combination.
#[derive(Clone, Debug, Default, PartialEq, Serialize)]
pub struct Uncertainty {
    /// Caller-supplied accuracy in metres.
    pub accuracy_m: Option<f64>,
    /// Dimensionless horizontal dilution of precision.
    pub hdop: Option<f64>,
    /// Dimensionless vertical dilution of precision.
    pub vdop: Option<f64>,
}
/// Validatable native-frame input.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Point {
    /// Tagged frame component object, flattened on the wire.
    #[serde(flatten)]
    pub frame: Frame,
    /// Independent measurement metadata.
    pub uncertainty: Uncertainty,
}
/// Retained original vertical metadata.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Height {
    /// Supplied source height in metres.
    pub value_m: f64,
    /// Source datum label.
    pub datum: String,
    /// Supplied geoid separation in metres.
    pub geoid_separation_m: Option<f64>,
}
/// Decoded precision footprint, independent of measured accuracy/distance bands.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct CellExtent {
    /// Ordered unclosed vertices; edges may cross the dateline.
    pub boundary: Vec<crate::result::Point>,
    /// Exact angular half-span for rectangular angular codes.
    pub half_lat_deg: Option<f64>,
    /// Exact angular half-span for rectangular angular codes.
    pub half_lon_deg: Option<f64>,
    /// MGRS cell side in projected metres.
    pub grid_size_m: Option<f64>,
    /// Maximum centre-to-listed-vertex great-circle distance, R=6371008.8 m.
    /// This spherical summary is neither a confidence radius nor a curved-edge bound.
    pub radius_m: f64,
}
/// Metadata from a single validated NMEA fix, never merged across timestamps.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct NmeaFix {
    /// GP or GN.
    pub talker: String,
    /// GGA, RMC or GLL.
    pub sentence: String,
    /// Original UTC field, if present.
    pub utc: Option<String>,
    /// GGA quality, if present.
    pub quality: Option<u8>,
    /// GGA satellites, if present.
    pub satellites: Option<u8>,
}
/// Pack-independent conversion output and complete query provenance.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct NormalizedPoint {
    /// Exact input or decoded representative, with only ellipsoidal canonical height.
    pub point: Geodetic,
    /// Canonical frame label.
    pub input_frame: String,
    /// Original supplied local origin.
    pub origin: Option<Origin>,
    /// Ordered stable operation identifiers.
    pub conversion: Vec<String>,
    /// Retained source height metadata.
    pub source_height: Option<Height>,
    /// Measurement metadata, independent of cell extent.
    pub uncertainty: Uncertainty,
    /// Decoded cell footprint, if applicable.
    pub cell_extent: Option<CellExtent>,
    /// Parsed NMEA metadata, if applicable.
    pub nmea: Option<NmeaFix>,
    /// Canonical H3 cell for dispatch to the legacy stored-ancestor lookup.
    pub h3_cell: Option<String>,
}
/// Stable structured coordinate diagnostic.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct CoordIssue {
    /// Snake-case error code.
    pub code: String,
    /// Actionable diagnostic, identical to the result hint.
    pub message: String,
}
/// Additive query provenance; all optional members serialize as null.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct QueryMetadata {
    /// Canonical frame label.
    pub input_frame: String,
    /// Original wire label; absent for typed calls/default frame.
    pub declared_frame: Option<String>,
    /// Exact or representative query, distinct from the result's H3 centre.
    pub normalized: Option<Geodetic>,
    /// Original local origin.
    pub origin: Option<Origin>,
    /// Ordered conversion identifiers.
    pub conversion: Vec<String>,
    /// Retained height metadata.
    pub source_height: Option<Height>,
    /// Measurement metadata.
    pub uncertainty: Uncertainty,
    /// Decoded cell extent.
    pub cell_extent: Option<CellExtent>,
    /// NMEA metadata.
    pub nmea: Option<NmeaFix>,
    /// Input error, if any.
    pub error: Option<CoordIssue>,
}
/// Legacy result fields plus an always-present query object.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct PointResult {
    /// Unchanged flat legacy lookup result.
    #[serde(flatten)]
    pub result: crate::result::LookupResult,
    /// Additive provenance, independent of evidence selection.
    pub query: QueryMetadata,
}

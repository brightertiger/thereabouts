//! Coordinate errors are input diagnostics, never pack errors.
use serde::Serialize;
use std::fmt;

/// A bounded parser, domain validation or conversion failure.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub enum CoordError {
    /// Frame outside the fixed native vocabulary.
    UnsupportedFrame {
        /// Supplied label.
        frame: String,
    },
    /// Required field absent.
    MissingField {
        /// Field name.
        field: String,
    },
    /// Wrong JSON or component type.
    InvalidType {
        /// Field name.
        field: String,
    },
    /// NaN or infinity.
    NonFinite {
        /// Field name.
        field: String,
    },
    /// Component outside its admission domain.
    OutOfRange {
        /// Field name.
        field: String,
    },
    /// Unknown or mutually inconsistent components.
    ConflictingFields {
        /// Conflicting field names.
        fields: Vec<String>,
    },
    /// No local origin.
    MissingOrigin,
    /// No reference for a short OLC.
    MissingReference,
    /// Cartesian conversion needs known ellipsoidal height.
    MissingEllipsoidalHeight,
    /// Geocentre, nonunique deep interior, or ambiguous pole orientation.
    UndefinedPosition,
    /// Bounded numerical inversion failed its residual check.
    NoConvergence,
    /// Malformed native text or cell identifier.
    InvalidSyntax {
        /// Native frame label.
        frame: String,
    },
    /// Missing or wrong NMEA checksum.
    InvalidChecksum,
    /// Void or absent NMEA fix.
    NoFix,
    /// A cell is finer than the native lookup supports.
    UnsupportedCellResolution {
        /// Cell frame.
        frame: String,
        /// Requested resolution.
        resolution: u8,
    },
}
impl CoordError {
    /// Stable snake-case wire diagnostic.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::UnsupportedFrame { .. } => "unsupported_frame",
            Self::MissingField { .. } => "missing_field",
            Self::InvalidType { .. } => "invalid_type",
            Self::NonFinite { .. } => "non_finite",
            Self::OutOfRange { .. } => "out_of_range",
            Self::ConflictingFields { .. } => "conflicting_fields",
            Self::MissingOrigin => "missing_origin",
            Self::MissingReference => "missing_reference",
            Self::MissingEllipsoidalHeight => "missing_ellipsoidal_height",
            Self::UndefinedPosition => "undefined_position",
            Self::NoConvergence => "no_convergence",
            Self::InvalidSyntax { .. } => "invalid_syntax",
            Self::InvalidChecksum => "invalid_checksum",
            Self::NoFix => "no_fix",
            Self::UnsupportedCellResolution { .. } => "unsupported_cell_resolution",
        }
    }
}
impl fmt::Display for CoordError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnsupportedFrame { frame } if frame.starts_with("crs:") => f.write_str("Thereabouts does not transform arbitrary CRSs; use GeoReconcile crs: support or pyproj, then pass WGS84 geodetic coordinates"),
            Self::UnsupportedFrame { frame } if frame == "llv" => f.write_str("Choose frame enu or ned and supply an origin; llv does not define axis order"),
            Self::UnsupportedFrame { frame } => write!(f, "Unsupported frame {frame}; choose geodetic (latlon/lla/llh), ecef, enu, ned, utm, mgrs, geohash, pluscode, h3, s2, dms, nmea, geojson or wkt"),
            Self::MissingField { field } => write!(f, "Coordinate field {field} is required"),
            Self::InvalidType { field } => write!(f, "Coordinate field {field} has an invalid type"),
            Self::NonFinite { field } => write!(f, "Coordinate field {field} must be finite"),
            Self::OutOfRange { field } => write!(f, "Coordinate field {field} is outside the supported range"),
            Self::ConflictingFields { fields } => write!(f, "Unknown or conflicting coordinate fields: {}", fields.join(", ")),
            Self::MissingOrigin => f.write_str("Frame enu/ned requires an explicit geodetic or ECEF origin"),
            Self::MissingReference => f.write_str("Short plus codes require a geodetic reference; use a full plus code otherwise"),
            Self::MissingEllipsoidalHeight => f.write_str("ECEF conversion requires ellipsoidal height or a supplied geoid separation; no geoid model is applied"),
            Self::UndefinedPosition => f.write_str("ECEF position or local-frame orientation is undefined; provide a valid position and a geodetic pole origin"),
            Self::NoConvergence => f.write_str("Coordinate conversion did not converge within the required residual; check the input domain"),
            Self::InvalidSyntax { frame } => write!(f, "Invalid {frame} syntax; supply one valid explicitly labelled coordinate"),
            Self::InvalidChecksum => f.write_str("NMEA checksum is missing or invalid"),
            Self::NoFix => f.write_str("NMEA sentence does not contain an active position fix"),
            Self::UnsupportedCellResolution { frame, resolution: _ } if frame == "h3" => f.write_str("H3 reverse queries support resolutions 0 through 8; use an explicit parent cell"),
            Self::UnsupportedCellResolution { frame, resolution } => write!(f, "Unsupported {frame} cell resolution {resolution}"),
        }
    }
}
impl std::error::Error for CoordError {}

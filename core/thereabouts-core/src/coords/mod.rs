//! Native coordinate frames, independent of packs and IO except the two reverse
//! adapters. Units are degrees/metres; the default is named WGS84 geodetic.
//!
//! Cell footprints describe decoded precision, not measured accuracy. Their
//! radius is a spherical centre-to-listed-vertex summary using R=6371008.8 m,
//! not a confidence interval or a guaranteed bound on curved edges. HDOP/VDOP
//! remain dimensionless. No vertical grid or arbitrary CRS transform is loaded.
//!
//! Wire input must pass through [`parse_point`]; direct typed input is revalidated
//! by [`normalize`]. Result points keep their legacy H3 centre meaning; `query`
//! contains the exact/representative normalized input, even without evidence.
// Small fixed mathematical tables and parser buffers are checked before indexing.
// Formula variable names and rational coefficients follow their source notation.
#![allow(
    clippy::indexing_slicing,
    clippy::many_single_char_names,
    clippy::similar_names,
    clippy::unreadable_literal,
    clippy::float_cmp
)]
mod cartesian;
mod cells;
mod error;
mod mgrs;
mod parse;
mod text;
mod types;
mod utm;
pub use cartesian::{ecef_to_enu, ecef_to_geodetic, enu_to_ecef, geodetic_to_ecef};
use cartesian::{geo, height, origin_data};
pub use error::CoordError;
pub use parse::parse_point;
use parse::{finite, range};
pub use types::*;
pub use utm::{geodetic_to_utm, utm_to_geodetic};

fn validate_uncertainty(u: &Uncertainty) -> Result<(), CoordError> {
    for (name, value) in [
        ("accuracy_m", u.accuracy_m),
        ("hdop", u.hdop),
        ("vdop", u.vdop),
    ] {
        if let Some(value) = value {
            finite(value, name)?;
            if value < 0.0 {
                return Err(range(name));
            }
        }
    }
    Ok(())
}
/// Validate and convert one typed input without reading a pack or performing IO.
/// All local origins, text domains, heights and uncertainty are checked again.
#[allow(clippy::too_many_lines)] // One explicit dispatcher, with maths in independent modules.
pub fn normalize(point: &Point) -> Result<NormalizedPoint, CoordError> {
    validate_uncertainty(&point.uncertainty)?;
    let mut out = NormalizedPoint {
        point: geo(0.0, 0.0),
        input_frame: point.frame.label().into(),
        origin: None,
        conversion: vec![],
        source_height: None,
        uncertainty: point.uncertainty.clone(),
        cell_extent: None,
        nmea: None,
        h3_cell: None,
    };
    let mut operations = Vec::<String>::new();
    let p = match &point.frame {
        Frame::Geodetic(p) => {
            operations.push("geodetic_identity".into());
            p.clone()
        }
        Frame::Ecef(p) => {
            let p = ecef_to_geodetic(p)?;
            operations.push("ecef_to_geodetic_wgs84".into());
            p
        }
        Frame::Enu { e, n, u, origin } | Frame::Ned { n, e, d: u, origin } => {
            let (_, _, mut origin_ops) = origin_data(origin)?;
            operations.append(&mut origin_ops);
            let ned = matches!(&point.frame, Frame::Ned { .. });
            if ned {
                finite(*u, "d")?;
                operations.push("ned_to_enu".into());
            }
            let xyz = enu_to_ecef(*e, *n, if ned { -*u } else { *u }, origin)?;
            operations.push("enu_to_ecef_wgs84".into());
            let p = ecef_to_geodetic(&xyz)?;
            operations.push("ecef_to_geodetic_wgs84".into());
            out.origin = Some(origin.clone());
            p
        }
        Frame::Utm(p) => {
            let p = utm_to_geodetic(p)?;
            operations.push("utm_inverse_wgs84_kruger6".into());
            p
        }
        Frame::Mgrs(s) => {
            let (p, extent, ups) = mgrs::decode(s)?;
            operations.push("mgrs_cell_center_wgs84".into());
            operations.push(
                if ups {
                    "ups_inverse_wgs84"
                } else {
                    "utm_inverse_wgs84_kruger6"
                }
                .into(),
            );
            out.cell_extent = Some(extent);
            p
        }
        Frame::Geohash(s) => {
            let (p, e) = cells::geohash(s)?;
            out.cell_extent = Some(e);
            operations.push("geohash_cell_center".into());
            p
        }
        Frame::Pluscode { value, reference } => {
            let (p, e, short) = cells::pluscode(value, reference.as_ref())?;
            if short {
                operations.push("pluscode_recover_short".into());
            }
            operations.push("pluscode_cell_center".into());
            out.cell_extent = Some(e);
            p
        }
        Frame::H3(s) => {
            let (p, e, cell) = cells::h3(s)?;
            out.cell_extent = Some(e);
            out.h3_cell = Some(cell);
            operations.push("h3_stored_ancestor".into());
            p
        }
        Frame::S2(s) => {
            let (p, e) = cells::s2(s)?;
            out.cell_extent = Some(e);
            operations.push("s2_cell_center".into());
            p
        }
        Frame::Dms(s) => {
            let p = text::dms(s)?;
            operations.push("dms_parse".into());
            p
        }
        Frame::Nmea(s) => {
            let (p, fix, hdop) = text::nmea(s)?;
            if let (Some(a), Some(b)) = (hdop, out.uncertainty.hdop)
                && a != b
            {
                return Err(CoordError::ConflictingFields {
                    fields: vec!["uncertainty.hdop".into(), "nmea.hdop".into()],
                });
            }
            out.uncertainty.hdop = out.uncertainty.hdop.or(hdop);
            out.nmea = Some(fix);
            operations.push("nmea_checksum_parse".into());
            p
        }
        Frame::GeoJson(values) => {
            let p = text::geojson(values)?;
            operations.push("geojson_lon_lat".into());
            p
        }
        Frame::Wkt(s) => {
            let p = text::wkt(s)?;
            operations.push("wkt_lon_lat".into());
            p
        }
    };
    let (p, source, converted) = height(&p)?;
    out.point = p;
    // A calculated ellipsoidal height is canonical, not a supplied source height.
    if matches!(
        point.frame,
        Frame::Geodetic(_) | Frame::GeoJson(_) | Frame::Wkt(_) | Frame::Nmea(_)
    ) {
        out.source_height = source;
    }
    if converted {
        operations.push("msl_plus_separation".into());
    }
    out.conversion = operations;
    Ok(out)
}
fn query(p: NormalizedPoint, declared: Option<&str>) -> QueryMetadata {
    QueryMetadata {
        input_frame: p.input_frame,
        declared_frame: declared.map(str::to_owned),
        normalized: Some(p.point),
        origin: p.origin,
        conversion: p.conversion,
        source_height: p.source_height,
        uncertainty: p.uncertainty,
        cell_extent: p.cell_extent,
        nmea: p.nmea,
        error: None,
    }
}
/// Create an ordinary `invalid_input` result with stable hint and query diagnostic.
/// Malformed coordinates are never echoed; normalized, origin and height are null.
#[must_use]
pub fn invalid_result(declared_frame: Option<&str>, error: &CoordError) -> PointResult {
    let mut result = crate::result::LookupResult::empty(crate::result::Status::InvalidInput);
    let message = error.to_string();
    result.hint = Some(message.clone());
    let input_frame = match declared_frame.unwrap_or("geodetic") {
        "latlon" | "lla" | "llh" => "geodetic",
        s => s,
    };
    PointResult {
        result,
        query: QueryMetadata {
            input_frame: input_frame.into(),
            declared_frame: declared_frame.map(str::to_owned),
            normalized: None,
            origin: None,
            conversion: vec![],
            source_height: None,
            uncertainty: Uncertainty::default(),
            cell_extent: None,
            nmea: None,
            error: Some(CoordIssue {
                code: error.code().into(),
                message,
            }),
        },
    }
}
fn reverse_normalized(
    pack: &crate::format::Pack,
    p: NormalizedPoint,
    evidence: bool,
    declared: Option<&str>,
) -> crate::Result<PointResult> {
    let result = if let Some(cell) = &p.h3_cell {
        pack.from_h3(cell, evidence)?
    } else {
        pack.reverse(p.point.lat, p.point.lon, evidence)?
    };
    Ok(PointResult {
        result,
        query: query(p, declared),
    })
}
/// Normalize typed input then reuse `Pack::reverse` or the unchanged H3 stored
/// ancestor lookup. Coordinate errors are ordinary results; pack errors propagate.
pub fn reverse_point(
    pack: &crate::format::Pack,
    point: &Point,
    evidence: bool,
) -> crate::Result<PointResult> {
    match normalize(point) {
        Ok(p) => reverse_normalized(pack, p, evidence, None),
        Err(e) => {
            let mut result = invalid_result(None, &e);
            result.query.input_frame = point.frame.label().into();
            Ok(result)
        }
    }
}
/// Parse a wire object through the same native normalizer, retaining its declared
/// label. Conversion metadata is present independently of `evidence`.
pub fn reverse_value(
    pack: &crate::format::Pack,
    value: &serde_json::Value,
    evidence: bool,
) -> crate::Result<PointResult> {
    let declared = value
        .get("frame")
        .and_then(serde_json::Value::as_str)
        .filter(|s| s.len() <= 1024);
    match parse_point(value).and_then(|p| normalize(&p)) {
        Ok(p) => reverse_normalized(pack, p, evidence, declared),
        Err(e) => Ok(invalid_result(declared, &e)),
    }
}

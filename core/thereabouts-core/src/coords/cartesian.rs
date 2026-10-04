//! WGS84 Cartesian conversion with bounded refinement and a forward residual gate.
use super::parse::{finite, range};
use super::{CoordError, Ecef, Geodetic, Height, Origin};
pub(super) const A: f64 = 6_378_137.0;
pub(super) const F: f64 = 1.0 / 298.257_223_563;
pub(super) const B: f64 = A * (1.0 - F);
pub(super) const E2: f64 = F * (2.0 - F);
pub(super) fn wrap(lon: f64) -> f64 {
    (lon + 180.0).rem_euclid(360.0) - 180.0
}
pub(super) fn geo(lat: f64, lon: f64) -> Geodetic {
    Geodetic {
        lat,
        lon,
        height: None,
        height_datum: None,
        geoid_separation: None,
    }
}
pub(super) fn height(point: &Geodetic) -> Result<(Geodetic, Option<Height>, bool), CoordError> {
    finite(point.lat, "lat")?;
    finite(point.lon, "lon")?;
    if !(-90.0..=90.0).contains(&point.lat) {
        return Err(range("lat"));
    }
    if !(-180.0..=180.0).contains(&point.lon) {
        return Err(range("lon"));
    }
    if let Some(h) = point.height {
        finite(h, "height")?;
    }
    if let Some(s) = point.geoid_separation {
        finite(s, "geoid_separation")?;
    }
    if point
        .height_datum
        .as_ref()
        .is_some_and(|d| d.is_empty() || d.len() > 64)
    {
        return Err(range("height_datum"));
    }
    if point.height.is_none() && (point.height_datum.is_some() || point.geoid_separation.is_some())
    {
        return Err(CoordError::ConflictingFields {
            fields: vec!["height".into(), "height_datum/geoid_separation".into()],
        });
    }
    let source = point.height.map(|h| Height {
        value_m: h,
        datum: point
            .height_datum
            .clone()
            .unwrap_or_else(|| "ellipsoid".into()),
        geoid_separation_m: point.geoid_separation,
    });
    let mut p = geo(point.lat, point.lon);
    let datum = point.height_datum.as_deref().unwrap_or("ellipsoid");
    let converted = datum == "msl" && point.height.is_some() && point.geoid_separation.is_some();
    p.height = if datum == "ellipsoid" {
        point.height
    } else if converted {
        point.height.zip(point.geoid_separation).map(|(h, s)| h + s)
    } else {
        None
    };
    if let Some(h) = p.height {
        finite(h, "height")?;
        p.height_datum = Some("ellipsoid".into());
    }
    Ok((p, source, converted))
}
/// Convert WGS84 geodetic degrees/metres to ECEF. Height must be known above the
/// ellipsoid, directly or as MSL plus an explicitly supplied geoid separation.
pub fn geodetic_to_ecef(point: &Geodetic) -> Result<Ecef, CoordError> {
    let (p, _, _) = height(point)?;
    let h = p.height.ok_or(CoordError::MissingEllipsoidalHeight)?;
    let (s, c) = p.lat.to_radians().sin_cos();
    let (sl, cl) = p.lon.to_radians().sin_cos();
    let n = A / (1.0 - E2 * s * s).sqrt();
    let c = if p.lat.abs() == 90.0 { 0.0 } else { c };
    let out = Ecef {
        x: (n + h) * c * cl,
        y: (n + h) * c * sl,
        z: (n * (1.0 - E2) + h) * s,
    };
    validate(&out)?;
    Ok(out)
}
fn validate(p: &Ecef) -> Result<(), CoordError> {
    finite(p.x, "x")?;
    finite(p.y, "y")?;
    finite(p.z, "z")?;
    Ok(())
}
/// Invert WGS84 ECEF using a Bowring seed and at most 16 Newton refinements.
/// The deep-interior evolute envelope is excluded; a forward XYZ residual must
/// be strictly below 1 mm. ECEF-derived poles use longitude zero.
pub fn ecef_to_geodetic(point: &Ecef) -> Result<Geodetic, CoordError> {
    validate(point)?;
    let p = point.x.hypot(point.y);
    let r = p.hypot(point.z);
    // All near-surface and satellite positions are well outside this envelope.
    // Inside it geodetic normal intersections can be nonunique.
    if r <= A * E2 / (1.0 - E2) {
        return Err(CoordError::UndefinedPosition);
    }
    if !r.is_finite() {
        return Err(CoordError::NoConvergence);
    }
    let theta = (point.z * A).atan2(p * B);
    let (st, ct) = theta.sin_cos();
    let mut phi = (point.z + E2 / (1.0 - E2) * B * st.powi(3)).atan2(p - E2 * A * ct.powi(3));
    for _ in 0..16 {
        let (s, c) = phi.sin_cos();
        let q = 1.0 - E2 * s * s;
        let n = A / q.sqrt();
        let dn = n * E2 * s * c / q;
        let residual = p * s - point.z * c - E2 * n * s * c;
        let derivative = p * c + point.z * s - E2 * (dn * s * c + n * (c * c - s * s));
        let delta = residual / derivative;
        if !delta.is_finite() {
            return Err(CoordError::NoConvergence);
        }
        phi -= delta;
        if delta.abs() < 2e-16 {
            break;
        }
    }
    if !(-std::f64::consts::FRAC_PI_2..=std::f64::consts::FRAC_PI_2).contains(&phi) {
        return Err(CoordError::UndefinedPosition);
    }
    let (s, c) = phi.sin_cos();
    let h = p * c + point.z * s - A * (1.0 - E2 * s * s).sqrt();
    let out = Geodetic {
        lat: phi.to_degrees(),
        lon: if p == 0.0 {
            0.0
        } else {
            wrap(point.y.atan2(point.x).to_degrees())
        },
        height: Some(h),
        height_datum: Some("ellipsoid".into()),
        geoid_separation: None,
    };
    let check = geodetic_to_ecef(&out)?;
    let residual = (check.x - point.x)
        .hypot(check.y - point.y)
        .hypot(check.z - point.z);
    if residual >= 0.001 || !residual.is_finite() {
        return Err(CoordError::NoConvergence);
    }
    Ok(out)
}
pub(super) fn origin_data(origin: &Origin) -> Result<(Ecef, Geodetic, Vec<String>), CoordError> {
    match origin {
        Origin::Ecef(p) => {
            if p.x == 0.0 && p.y == 0.0 {
                return Err(CoordError::UndefinedPosition);
            }
            Ok((
                p.clone(),
                ecef_to_geodetic(p)?,
                vec!["ecef_to_geodetic_wgs84".into()],
            ))
        }
        Origin::Geodetic(p) => {
            let (mut p, _, converted) = height(p)?;
            let mut operations = Vec::new();
            if converted {
                operations.push("msl_plus_separation".into());
            }
            if p.height.is_none() {
                if let Origin::Geodetic(original) = origin
                    && original.height.is_some()
                {
                    return Err(CoordError::MissingEllipsoidalHeight);
                }
                p.height = Some(0.0);
                p.height_datum = Some("ellipsoid".into());
                operations.push("origin_height_assumed_zero".into());
            }
            let xyz = geodetic_to_ecef(&p)?;
            if xyz.x.hypot(xyz.y).hypot(xyz.z) <= A * E2 / (1.0 - E2) {
                return Err(CoordError::UndefinedPosition);
            }
            operations.push("origin_geodetic_to_ecef_wgs84".into());
            Ok((xyz, p, operations))
        }
    }
}
/// Translate and rotate an explicit local Cartesian tangent vector into ECEF.
/// This is valid for large offsets and does not approximate a surface distance.
pub fn enu_to_ecef(e: f64, n: f64, u: f64, origin: &Origin) -> Result<Ecef, CoordError> {
    finite(e, "e")?;
    finite(n, "n")?;
    finite(u, "u")?;
    let (o, p, _) = origin_data(origin)?;
    let (s, c) = p.lat.to_radians().sin_cos();
    let (sl, cl) = p.lon.to_radians().sin_cos();
    let out = Ecef {
        x: o.x - sl * e - s * cl * n + c * cl * u,
        y: o.y + cl * e - s * sl * n + c * sl * u,
        z: o.z + c * n + s * u,
    };
    validate(&out)?;
    Ok(out)
}
/// Inverse rigid rotation/translation, returning east, north, up in metres.
pub fn ecef_to_enu(point: &Ecef, origin: &Origin) -> Result<[f64; 3], CoordError> {
    validate(point)?;
    let (o, p, _) = origin_data(origin)?;
    let (s, c) = p.lat.to_radians().sin_cos();
    let (sl, cl) = p.lon.to_radians().sin_cos();
    let (x, y, z) = (point.x - o.x, point.y - o.y, point.z - o.z);
    let out = [
        -sl * x + cl * y,
        -s * cl * x - s * sl * y + c * z,
        c * cl * x + c * sl * y + s * z,
    ];
    for v in out {
        finite(v, "local_offset")?;
    }
    Ok(out)
}

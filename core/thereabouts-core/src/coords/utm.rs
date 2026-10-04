//! WGS84 transverse Mercator: Krüger series through n^6 (Karney 2011).
//! Explicit zones are retained. Automatic zones use Norway/Svalbard exceptions.
use super::cartesian::{A, E2, F, geo, height, wrap};
use super::parse::{finite, range};
use super::{CoordError, Geodetic, Hemisphere, Utm};
const K0: f64 = 0.9996;
pub(super) const BANDS: &str = "CDEFGHJKLMNPQRSTUVWX";
fn coefficients() -> (f64, [f64; 6], [f64; 6]) {
    let n = F / (2.0 - F);
    let n2 = n * n;
    let n3 = n2 * n;
    let n4 = n2 * n2;
    let n5 = n4 * n;
    let n6 = n3 * n3;
    let a = A / (1.0 + n) * (1.0 + n2 / 4.0 + n4 / 64.0 + n6 / 256.0);
    let alpha = [
        n / 2.0 - 2.0 * n2 / 3.0 + 5.0 * n3 / 16.0 + 41.0 * n4 / 180.0 - 127.0 * n5 / 288.0
            + 7891.0 * n6 / 37800.0,
        13.0 * n2 / 48.0 - 3.0 * n3 / 5.0 + 557.0 * n4 / 1440.0 + 281.0 * n5 / 630.0
            - 1983433.0 * n6 / 1935360.0,
        61.0 * n3 / 240.0 - 103.0 * n4 / 140.0 + 15061.0 * n5 / 26880.0 + 167603.0 * n6 / 181440.0,
        49561.0 * n4 / 161280.0 - 179.0 * n5 / 168.0 + 6601661.0 * n6 / 7257600.0,
        34729.0 * n5 / 80640.0 - 3418889.0 * n6 / 1995840.0,
        212378941.0 * n6 / 319334400.0,
    ];
    let beta = [
        n / 2.0 - 2.0 * n2 / 3.0 + 37.0 * n3 / 96.0 - n4 / 360.0 - 81.0 * n5 / 512.0
            + 96199.0 * n6 / 604800.0,
        n2 / 48.0 + n3 / 15.0 - 437.0 * n4 / 1440.0 + 46.0 * n5 / 105.0
            - 1118711.0 * n6 / 3870720.0,
        17.0 * n3 / 480.0 - 37.0 * n4 / 840.0 - 209.0 * n5 / 4480.0 + 5569.0 * n6 / 90720.0,
        4397.0 * n4 / 161280.0 - 11.0 * n5 / 504.0 - 830251.0 * n6 / 7257600.0,
        4583.0 * n5 / 161280.0 - 108847.0 * n6 / 3991680.0,
        20648693.0 * n6 / 638668800.0,
    ];
    (a, alpha, beta)
}
pub(super) fn band_bounds(band: char) -> Result<(f64, f64), CoordError> {
    let index = BANDS.find(band).ok_or_else(|| range("band"))?;
    let min = -80.0 + 8.0 * f64::from(u8::try_from(index).map_err(|_| range("band"))?);
    Ok((min, if band == 'X' { 84.0 } else { min + 8.0 }))
}
fn hemisphere(p: &Utm) -> Result<bool, CoordError> {
    let band_north = p
        .band
        .map(|b| band_bounds(b).map(|_| b >= 'N'))
        .transpose()?;
    let explicit = p.hemisphere.as_ref().map(|h| *h == Hemisphere::North);
    if let (Some(a), Some(b)) = (band_north, explicit)
        && a != b
    {
        return Err(CoordError::ConflictingFields {
            fields: vec!["hemisphere".into(), "band".into()],
        });
    }
    explicit
        .or(band_north)
        .ok_or_else(|| CoordError::MissingField {
            field: "hemisphere or band".into(),
        })
}
/// Invert a zone/hemisphere (or band) UTM input and validate its geographic domain.
pub fn utm_to_geodetic(point: &Utm) -> Result<Geodetic, CoordError> {
    let north = hemisphere(point)?;
    if !(1..=60).contains(&point.zone) {
        return Err(range("zone"));
    }
    finite(point.easting, "easting")?;
    finite(point.northing, "northing")?;
    if !(100_000.0..=900_000.0).contains(&point.easting) {
        return Err(range("easting"));
    }
    if !(0.0..=10_000_000.0).contains(&point.northing) {
        return Err(range("northing"));
    }
    let p = inverse_raw(point.zone, north, point.easting, point.northing)?;
    if p.lat < -80.0 - 2e-12 || p.lat > 84.0 + 2e-12 {
        return Err(range("lat"));
    }
    if (north && p.lat < -2e-12) || (!north && p.lat > 2e-12) {
        return Err(range("hemisphere"));
    }
    if let Some(b) = point.band {
        let (lo, hi) = band_bounds(b)?;
        if p.lat < lo - 2e-12 || p.lat > hi + 2e-12 {
            return Err(range("band"));
        }
    }
    Ok(p)
}
pub(super) fn inverse_raw(
    zone: u8,
    north: bool,
    easting: f64,
    northing: f64,
) -> Result<Geodetic, CoordError> {
    let (a, _, beta) = coefficients();
    let xi = (northing - if north { 0.0 } else { 10_000_000.0 }) / (K0 * a);
    let eta = (easting - 500_000.0) / (K0 * a);
    let (mut xp, mut ep) = (xi, eta);
    for (j, b) in (1_u8..=6).zip(beta) {
        let k = 2.0 * f64::from(j);
        xp -= b * (k * xi).sin() * (k * eta).cosh();
        ep -= b * (k * xi).cos() * (k * eta).sinh();
    }
    let taup = xp.sin() / ep.sinh().hypot(xp.cos());
    let target = taup.asinh();
    let e = E2.sqrt();
    let mut phi = taup.atan();
    for _ in 0..10 {
        let (s, c) = phi.sin_cos();
        let d = (phi.tan().asinh() - e * (e * s).atanh() - target) * c * (1.0 - E2 * s * s)
            / (1.0 - E2);
        phi -= d;
        if d.abs() < 2e-16 {
            break;
        }
    }
    let lat = phi.to_degrees();
    let lon = wrap(ep.sinh().atan2(xp.cos()).to_degrees() + f64::from(zone) * 6.0 - 183.0);
    finite(lat, "lat")?;
    finite(lon, "lon")?;
    Ok(geo(lat, lon))
}
/// Project WGS84 degrees with the n^6 series, choosing a standard zone unless
/// explicitly supplied. Height is validated but does not affect the projection.
pub fn geodetic_to_utm(point: &Geodetic, zone: Option<u8>) -> Result<Utm, CoordError> {
    height(point)?;
    if !(-80.0..=84.0).contains(&point.lat) {
        return Err(range("lat"));
    }
    let z = zone.unwrap_or_else(|| auto_zone(point.lat, point.lon));
    if !(1..=60).contains(&z) {
        return Err(range("zone"));
    }
    let (easting, northing) = forward_raw(point.lat, point.lon, z, point.lat >= 0.0)?;
    // Beyond this central strip the truncated series is not the admitted UTM domain.
    if !(100_000.0..=900_000.0).contains(&easting) || !(0.0..=10_000_000.0).contains(&northing) {
        return Err(range("utm"));
    }
    let band = BANDS
        .chars()
        .enumerate()
        .find(|(_, b)| {
            band_bounds(*b).is_ok_and(|(lo, hi)| {
                point.lat >= lo && (point.lat < hi || (*b == 'X' && point.lat == 84.0))
            })
        })
        .map(|(_, b)| b);
    Ok(Utm {
        zone: z,
        hemisphere: Some(if point.lat >= 0.0 {
            Hemisphere::North
        } else {
            Hemisphere::South
        }),
        band,
        easting,
        northing,
    })
}
fn auto_zone(lat: f64, lon: f64) -> u8 {
    let mut z = (1_u8..=60)
        .find(|z| lon < f64::from(*z) * 6.0 - 180.0)
        .unwrap_or(60);
    if (56.0..64.0).contains(&lat) && (3.0..12.0).contains(&lon) {
        z = 32;
    }
    if (72.0..=84.0).contains(&lat) {
        for (lo, hi, zone) in [
            (0.0, 9.0, 31),
            (9.0, 21.0, 33),
            (21.0, 33.0, 35),
            (33.0, 42.0, 37),
        ] {
            if (lo..hi).contains(&lon) {
                z = zone;
            }
        }
    }
    z
}
pub(super) fn forward_raw(
    lat: f64,
    lon: f64,
    zone: u8,
    north: bool,
) -> Result<(f64, f64), CoordError> {
    let phi = lat.to_radians();
    let lam = wrap(lon - (f64::from(zone) * 6.0 - 183.0)).to_radians();
    if lam.abs() > std::f64::consts::FRAC_PI_4 {
        return Err(range("zone"));
    }
    let e = E2.sqrt();
    let taup = (phi.tan().asinh() - e * (e * phi.sin()).atanh()).sinh();
    let xi = taup.atan2(lam.cos());
    let eta = (lam.sin() / taup.hypot(lam.cos())).asinh();
    let (a, alpha, _) = coefficients();
    let (mut x, mut y) = (xi, eta);
    for (j, b) in (1_u8..=6).zip(alpha) {
        let k = 2.0 * f64::from(j);
        x += b * (k * xi).sin() * (k * eta).cosh();
        y += b * (k * xi).cos() * (k * eta).sinh();
    }
    Ok((
        500_000.0 + K0 * a * y,
        K0 * a * x + if north { 0.0 } else { 10_000_000.0 },
    ))
}

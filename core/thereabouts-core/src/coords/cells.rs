//! Exact angular geocodes and small native S2 face/Hilbert decoding.
use super::cartesian::{geo, height, wrap};
use super::parse::syntax;
use super::{CellExtent, CellId, CoordError, Geodetic};
use crate::result::Point;
pub(super) fn extent(
    centre: &Geodetic,
    boundary: Vec<Point>,
    half_lat: Option<f64>,
    half_lon: Option<f64>,
    grid: Option<f64>,
) -> CellExtent {
    let radius = boundary
        .iter()
        .map(|p| {
            let dlat = (p.lat - centre.lat).to_radians();
            let dlon = wrap(p.lon - centre.lon).to_radians();
            let a = (dlat / 2.0).sin().powi(2)
                + centre.lat.to_radians().cos()
                    * p.lat.to_radians().cos()
                    * (dlon / 2.0).sin().powi(2);
            2.0 * 6_371_008.8 * a.clamp(0.0, 1.0).sqrt().asin()
        })
        .fold(0.0, f64::max);
    CellExtent {
        boundary,
        half_lat_deg: half_lat,
        half_lon_deg: half_lon,
        grid_size_m: grid,
        radius_m: radius,
    }
}
fn rectangle(s: f64, w: f64, n: f64, e: f64) -> (Geodetic, CellExtent) {
    let p = geo(s.midpoint(n), w.midpoint(e));
    let boundary = vec![
        Point { lat: s, lon: w },
        Point { lat: s, lon: e },
        Point { lat: n, lon: e },
        Point { lat: n, lon: w },
    ];
    let extent = extent(&p, boundary, Some((n - s) / 2.0), Some((e - w) / 2.0), None);
    (p, extent)
}
pub(super) fn geohash(s: &str) -> Result<(Geodetic, CellExtent), CoordError> {
    if s.is_empty() || s.len() > 12 || !s.is_ascii() {
        return Err(syntax("geohash"));
    }
    let (mut south, mut north, mut west, mut east) = (-90.0, 90.0, -180.0, 180.0);
    let mut longitude = true;
    for c in s.bytes() {
        let value = b"0123456789bcdefghjkmnpqrstuvwxyz"
            .iter()
            .position(|b| *b == c.to_ascii_lowercase())
            .ok_or_else(|| syntax("geohash"))?;
        for bit in (0..5).rev() {
            let (lo, hi) = if longitude {
                (&mut west, &mut east)
            } else {
                (&mut south, &mut north)
            };
            let mid = f64::midpoint(*lo, *hi);
            if value & (1 << bit) == 0 {
                *hi = mid;
            } else {
                *lo = mid;
            }
            longitude = !longitude;
        }
    }
    Ok(rectangle(south, west, north, east))
}
const OLC: &[u8] = b"23456789CFGHJMPQRVWX";
fn olc_digit(b: u8) -> Result<u8, CoordError> {
    OLC.iter()
        .position(|x| *x == b)
        .and_then(|n| u8::try_from(n).ok())
        .ok_or_else(|| syntax("pluscode"))
}
fn olc_encode_prefix(reference: &Geodetic) -> String {
    let mut lat = (if reference.lat == 90.0 {
        90.0 - 0.000125
    } else {
        reference.lat
    }) + 90.0;
    let mut lon = wrap(reference.lon) + 180.0;
    let mut s = String::new();
    for size in [20.0, 1.0, 0.05, 0.0025, 0.000125] {
        // The digit search avoids float-to-integer conversion and has fixed work.
        let y = (0_u8..20)
            .rev()
            .find(|v| lat >= f64::from(*v) * size)
            .unwrap_or(0);
        let x = (0_u8..20)
            .rev()
            .find(|v| lon >= f64::from(*v) * size)
            .unwrap_or(0);
        s.push(char::from(OLC[usize::from(y)]));
        s.push(char::from(OLC[usize::from(x)]));
        lat -= f64::from(y) * size;
        lon -= f64::from(x) * size;
    }
    s
}
pub(super) fn pluscode(
    value: &str,
    reference: Option<&Geodetic>,
) -> Result<(Geodetic, CellExtent, bool), CoordError> {
    if value.len() > 16 || !value.is_ascii() {
        return Err(syntax("pluscode"));
    }
    if let Some(r) = reference {
        height(r)?;
    }
    let mut code = value.to_ascii_uppercase();
    let separator = code.find('+').ok_or_else(|| syntax("pluscode"))?;
    if separator > 8
        || separator % 2 != 0
        || code.bytes().filter(|b| *b == b'+').count() != 1
        || code.len() - separator - 1 == 1
    {
        return Err(syntax("pluscode"));
    }
    let short = separator < 8;
    let missing = 8 - separator;
    if short {
        if code.contains('0') {
            return Err(syntax("pluscode"));
        }
        let reference = reference.ok_or(CoordError::MissingReference)?;
        let prefix = olc_encode_prefix(reference);
        code = format!("{}{}", &prefix[..missing], code);
    }
    let tail = &code[9..];
    let before = &code[..8];
    let significant = if let Some(z) = before.find('0') {
        if z < 2 || z % 2 != 0 || !before[z..].bytes().all(|b| b == b'0') || !tail.is_empty() {
            return Err(syntax("pluscode"));
        }
        before[..z].to_owned()
    } else {
        format!("{before}{tail}")
    };
    let len = significant.len();
    if !(2..=15).contains(&len) || (len < 10 && len % 2 != 0) {
        return Err(syntax("pluscode"));
    }
    let digits: Vec<_> = significant
        .bytes()
        .map(olc_digit)
        .collect::<Result<_, _>>()?;
    if digits[0] >= 9 || digits[1] >= 18 {
        return Err(syntax("pluscode"));
    }
    let (mut lat, mut lon) = (-90.0, -180.0);
    let (mut dy, mut dx) = (20.0, 20.0);
    for (i, pair) in digits[..len.min(10)].as_chunks::<2>().0.iter().enumerate() {
        let size = [20.0, 1.0, 0.05, 0.0025, 0.000125][i];
        lat += f64::from(pair[0]) * size;
        lon += f64::from(pair[1]) * size;
        dy = size;
        dx = size;
    }
    for digit in digits.iter().skip(10) {
        dy /= 5.0;
        dx /= 4.0;
        lat += f64::from(digit / 4) * dy;
        lon += f64::from(digit % 4) * dx;
    }
    if short {
        let r = reference.ok_or(CoordError::MissingReference)?;
        let power = i32::try_from(missing / 2).map_err(|_| syntax("pluscode"))?;
        let resolution = 20_f64.powi(2 - power);
        let half = resolution / 2.0;
        let centre_lat = lat + dy / 2.0;
        let centre_lon = lon + dx / 2.0;
        if r.lat + half < centre_lat && centre_lat - resolution >= -90.0 {
            lat -= resolution;
        } else if r.lat - half > centre_lat && centre_lat + resolution <= 90.0 {
            lat += resolution;
        }
        let diff = wrap(centre_lon - r.lon);
        if diff > half {
            lon -= resolution;
        } else if diff < -half {
            lon += resolution;
        }
        lon = wrap(lon);
    }
    let (p, mut e) = rectangle(lat, lon, lat + dy, lon + dx);
    e.half_lat_deg = Some(dy / 2.0);
    e.half_lon_deg = Some(dx / 2.0);
    Ok((p, e, short))
}
pub(super) fn h3(value: &CellId) -> Result<(Geodetic, CellExtent, String), CoordError> {
    use h3o::{CellIndex, LatLng};
    let cell = match value {
        CellId::Integer(n) => CellIndex::try_from(*n).map_err(|_| syntax("h3"))?,
        CellId::Text(s) => {
            if s.len() != 15 || !s.bytes().all(|c| c.is_ascii_hexdigit()) {
                return Err(syntax("h3"));
            }
            s.parse::<CellIndex>().map_err(|_| syntax("h3"))?
        }
    };
    let resolution = u8::from(cell.resolution());
    if resolution > 8 {
        return Err(CoordError::UnsupportedCellResolution {
            frame: "h3".into(),
            resolution,
        });
    }
    let ll = LatLng::from(cell);
    let p = geo(ll.lat(), wrap(ll.lng()));
    let boundary = cell
        .boundary()
        .iter()
        .map(|v| Point {
            lat: v.lat(),
            lon: wrap(v.lng()),
        })
        .collect();
    let e = extent(&p, boundary, None, None, None);
    Ok((p, e, cell.to_string()))
}
fn s2_xyz(face: u8, u: f64, v: f64) -> [f64; 3] {
    match face {
        0 => [1.0, u, v],
        1 => [-u, 1.0, v],
        2 => [-u, -v, 1.0],
        3 => [-1.0, -v, -u],
        4 => [v, -1.0, -u],
        _ => [v, u, -1.0],
    }
}
fn s2_point(face: u8, s: f64, t: f64) -> Geodetic {
    fn uv(s: f64) -> f64 {
        if s >= 0.5 {
            (4.0 * s * s - 1.0) / 3.0
        } else {
            (1.0 - 4.0 * (1.0 - s).powi(2)) / 3.0
        }
    }
    let [x, y, z] = s2_xyz(face, uv(s), uv(t));
    geo(
        z.atan2(x.hypot(y)).to_degrees(),
        wrap(y.atan2(x).to_degrees()),
    )
}
pub(super) fn s2(value: &CellId) -> Result<(Geodetic, CellExtent), CoordError> {
    const POS_TO_IJ: [[u8; 4]; 4] = [[0, 1, 3, 2], [0, 2, 3, 1], [3, 2, 0, 1], [3, 1, 0, 2]];
    const POS_TO_ORIENTATION: [usize; 4] = [1, 0, 0, 3];
    let id = match value {
        CellId::Integer(n) => *n,
        CellId::Text(s) => {
            if s.is_empty() || s.len() > 16 || !s.bytes().all(|b| b.is_ascii_hexdigit()) {
                return Err(syntax("s2"));
            }
            let n = u64::from_str_radix(s, 16).map_err(|_| syntax("s2"))?;
            n << (4 * (16 - s.len()))
        }
    };
    let face = u8::try_from(id >> 61).map_err(|_| syntax("s2"))?;
    let zeros = id.trailing_zeros();
    if id == 0 || face > 5 || zeros > 60 || zeros % 2 != 0 {
        return Err(syntax("s2"));
    }
    let level = (60 - zeros) / 2;
    let (mut i, mut j) = (0_u32, 0_u32);
    let mut orientation = usize::from(face & 1);
    // S2's four Hilbert orientations: swap=1, invert=2. Tables are 16 bytes.
    for depth in 0..level {
        let pos = usize::try_from((id >> (59 - 2 * depth)) & 3).map_err(|_| syntax("s2"))?;
        let ij = POS_TO_IJ[orientation][pos];
        i = (i << 1) | u32::from(ij >> 1);
        j = (j << 1) | u32::from(ij & 1);
        orientation ^= POS_TO_ORIENTATION[pos];
    }
    let size = f64::from(1_u32 << level);
    let s = f64::from(i) / size;
    let t = f64::from(j) / size;
    let d = 1.0 / size;
    let p = s2_point(face, s + d / 2.0, t + d / 2.0);
    let boundary = [(s, t), (s + d, t), (s + d, t + d), (s, t + d)]
        .into_iter()
        .map(|(s, t)| {
            let p = s2_point(face, s, t);
            Point {
                lat: p.lat,
                lon: p.lon,
            }
        })
        .collect();
    let e = extent(&p, boundary, None, None, None);
    Ok((p, e))
}

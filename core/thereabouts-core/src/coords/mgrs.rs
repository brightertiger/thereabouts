//! MGRS lettering, northing cycles and UTM/UPS cell-centre decoding.
use super::cartesian::{A, E2, geo, wrap};
use super::cells::extent;
use super::parse::syntax;
use super::utm::{band_bounds, forward_raw, inverse_raw};
use super::{CellExtent, CoordError, Geodetic};
use crate::result::Point;
fn index(letters: &str, letter: u8) -> Result<u8, CoordError> {
    letters
        .bytes()
        .position(|c| c == letter)
        .and_then(|n| u8::try_from(n).ok())
        .ok_or_else(|| syntax("mgrs"))
}
fn digits(s: &str) -> Result<(f64, f64, f64), CoordError> {
    if s.len() > 10 || !s.len().is_multiple_of(2) || !s.bytes().all(|c| c.is_ascii_digit()) {
        return Err(syntax("mgrs"));
    }
    let half = s.len() / 2;
    let size = 10_f64.powi(5 - i32::try_from(half).map_err(|_| syntax("mgrs"))?);
    if s.is_empty() {
        return Ok((0.0, 0.0, size));
    }
    let x = s[..half].parse::<u32>().map_err(|_| syntax("mgrs"))?;
    let y = s[half..].parse::<u32>().map_err(|_| syntax("mgrs"))?;
    Ok((f64::from(x) * size, f64::from(y) * size, size))
}
pub(super) fn decode(value: &str) -> Result<(Geodetic, CellExtent, bool), CoordError> {
    if value.len() > 64 || !value.is_ascii() {
        return Err(syntax("mgrs"));
    }
    let text: String = value
        .bytes()
        .filter(|c| !c.is_ascii_whitespace())
        .map(|c| char::from(c.to_ascii_uppercase()))
        .collect();
    let prefix = text.bytes().take_while(u8::is_ascii_digit).count();
    if text.len() < prefix + 3 {
        return Err(syntax("mgrs"));
    }
    let letters = &text.as_bytes()[prefix..prefix + 3];
    let (x, y, size) = digits(&text[prefix + 3..])?;
    if prefix == 0 {
        return ups(letters, x, y, size);
    }
    if prefix > 2 {
        return Err(syntax("mgrs"));
    }
    let zone = text[..prefix].parse::<u8>().map_err(|_| syntax("mgrs"))?;
    if !(1..=60).contains(&zone) {
        return Err(syntax("mgrs"));
    }
    let band = char::from(letters[0]);
    let (lo, hi) = band_bounds(band)?;
    if band == 'X' && [32, 34, 36].contains(&zone) {
        return Err(syntax("mgrs"));
    }
    let cols = match (zone - 1) % 3 {
        0 => "ABCDEFGH",
        1 => "JKLMNPQR",
        _ => "STUVWXYZ",
    };
    let e = 100_000.0 * (f64::from(index(cols, letters[1])?) + 1.0) + x;
    let row = index("ABCDEFGHJKLMNPQRSTUV", letters[2])?;
    let row = (row + 20 - if zone % 2 == 0 { 5 } else { 0 }) % 20;
    let base = 100_000.0 * f64::from(row) + y;
    let north = band >= 'N';
    let mut selected = None;
    for cycle in 0_u8..=5 {
        let n = base + 2_000_000.0 * f64::from(cycle);
        if n + size > 10_000_000.0 {
            continue;
        }
        // Latitude extrema of a projected rectangle occur on its north/south
        // edges, at endpoints or the central meridian. Test square intersection,
        // not the representative centre's band (which can be the next band).
        let mut min = f64::INFINITY;
        let mut max = f64::NEG_INFINITY;
        for ee in [e, e + size, 500_000.0_f64.clamp(e, e + size)] {
            for nn in [n, n + size] {
                let p = inverse_raw(zone, north, ee, nn)?;
                min = min.min(p.lat);
                max = max.max(p.lat);
            }
        }
        if max > lo + 1e-11 && min < hi - 1e-11 {
            selected = Some(n);
            break;
        }
    }
    let n = selected.ok_or_else(|| syntax("mgrs"))?;
    if !zone_intersects(zone, band, e, n, size)? {
        return Err(syntax("mgrs"));
    }
    let p = inverse_raw(zone, north, e + size / 2.0, n + size / 2.0)?;
    let boundary = [(e, n), (e + size, n), (e + size, n + size), (e, n + size)]
        .into_iter()
        .map(|(e, n)| {
            inverse_raw(zone, north, e, n).map(|p| Point {
                lat: p.lat,
                lon: p.lon,
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    let ext = extent(&p, boundary, None, None, Some(size));
    Ok((p, ext, false))
}
fn ups(
    letters: &[u8],
    x: f64,
    y: f64,
    size: f64,
) -> Result<(Geodetic, CellExtent, bool), CoordError> {
    let (north, west, cols, offset) = match letters[0] {
        b'A' => (false, true, "JKLPQRSTUXYZ", 8.0),
        b'B' => (false, false, "ABCFGHJKLPQR", 20.0),
        b'Y' => (true, true, "RSTUXYZ", 13.0),
        b'Z' => (true, false, "ABCFGHJ", 20.0),
        _ => return Err(syntax("mgrs")),
    };
    let rows = if north {
        "ABCDEFGHJKLMNP"
    } else {
        "ABCDEFGHJKLMNPQRSTUVWXYZ"
    };
    let e = (offset + f64::from(index(cols, letters[1])?)) * 100_000.0 + x;
    let n =
        ((if north { 13.0 } else { 8.0 }) + f64::from(index(rows, letters[2])?)) * 100_000.0 + y;
    if (west && e + size > 2_000_000.0) || (!west && e < 2_000_000.0) {
        return Err(syntax("mgrs"));
    }
    let p = ups_inverse(north, e + size / 2.0, n + size / 2.0)?;
    let boundary = [(e, n), (e + size, n), (e + size, n + size), (e, n + size)]
        .into_iter()
        .map(|(e, n)| {
            ups_inverse(north, e, n).map(|p| Point {
                lat: p.lat,
                lon: p.lon,
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    // Closest point to the pole establishes cap/square intersection even when
    // the centre lies outside the cap; equality is an admitted cap boundary.
    let near = ups_inverse(
        north,
        2_000_000.0_f64.clamp(e, e + size),
        2_000_000.0_f64.clamp(n, n + size),
    )?;
    if (north && near.lat < 84.0) || (!north && near.lat > -80.0) {
        return Err(syntax("mgrs"));
    }
    let ext = extent(&p, boundary, None, None, Some(size));
    Ok((p, ext, true))
}
fn ups_inverse(north: bool, easting: f64, northing: f64) -> Result<Geodetic, CoordError> {
    let x = easting - 2_000_000.0;
    let y = northing - 2_000_000.0;
    let rho = x.hypot(y);
    if rho == 0.0 {
        return Ok(geo(if north { 90.0 } else { -90.0 }, 0.0));
    }
    let e = E2.sqrt();
    let c = ((1.0 + e).powf(1.0 + e) * (1.0 - e).powf(1.0 - e)).sqrt();
    let t = rho * c / (2.0 * A * 0.994);
    let mut phi = std::f64::consts::FRAC_PI_2 - 2.0 * t.atan();
    let mut converged = false;
    for _ in 0..12 {
        let es = e * phi.sin();
        let next = std::f64::consts::FRAC_PI_2
            - 2.0 * (t * ((1.0 - es) / (1.0 + es)).powf(e / 2.0)).atan();
        if (next - phi).abs() < 2e-15 {
            converged = true;
            phi = next;
            break;
        }
        phi = next;
    }
    if !converged {
        return Err(CoordError::NoConvergence);
    }
    let lon = x.atan2(if north { -y } else { y }).to_degrees();
    Ok(geo(
        if north {
            phi.to_degrees()
        } else {
            -phi.to_degrees()
        },
        wrap(lon),
    ))
}

// Check the actual grid-zone designation footprint, including Norway/Svalbard.
// Projected geographic edges are monotone after splitting latitude edges at
// the central meridian. Bounded bisection clips each edge to the square's E
// interval, then checks its N interval; no sampling grid or centre-only test.
fn zone_intersects(zone: u8, band: char, e: f64, n: f64, size: f64) -> Result<bool, CoordError> {
    let (south, north_lat) = band_bounds(band)?;
    let north = band >= 'N';
    let central = f64::from(zone) * 6.0 - 183.0;
    let (mut west, mut east) = (central - 3.0, central + 3.0);
    if band == 'V' {
        match zone {
            31 => east = 3.0,
            32 => west = 3.0,
            _ => (),
        }
    }
    if band == 'X' {
        match zone {
            31 => east = 9.0,
            33 => {
                west = 9.0;
                east = 21.0;
            }
            35 => {
                west = 21.0;
                east = 33.0;
            }
            37 => west = 33.0,
            _ => (),
        }
    }
    for (x, y) in [(e, n), (e + size, n), (e + size, n + size), (e, n + size)] {
        let p = inverse_raw(zone, north, x, y)?;
        let lon = central + wrap(p.lon - central);
        if p.lat > south && p.lat < north_lat && lon > west && lon < east {
            return Ok(true);
        }
    }
    let edges = [
        ((south, west), (north_lat, west)),
        ((south, east), (north_lat, east)),
        ((south, west), (south, central.clamp(west, east))),
        ((south, central.clamp(west, east)), (south, east)),
        ((north_lat, west), (north_lat, central.clamp(west, east))),
        ((north_lat, central.clamp(west, east)), (north_lat, east)),
    ];
    for (a, b) in edges {
        let project =
            |t: f64| forward_raw(a.0 + t * (b.0 - a.0), a.1 + t * (b.1 - a.1), zone, north);
        let (x0, y0) = project(0.0)?;
        let (x1, y1) = project(1.0)?;
        if x0.max(x1) < e || x0.min(x1) > e + size || y0.max(y1) < n || y0.min(y1) > n + size {
            continue;
        }
        let increasing = x1 >= x0;
        let root = |target: f64| -> Result<f64, CoordError> {
            if (increasing && target <= x0) || (!increasing && target >= x0) {
                return Ok(0.0);
            }
            if (increasing && target >= x1) || (!increasing && target <= x1) {
                return Ok(1.0);
            }
            let (mut lo, mut hi) = (0.0_f64, 1.0_f64);
            for _ in 0..52 {
                let mid = lo.midpoint(hi);
                if (project(mid)?.0 < target) == increasing {
                    lo = mid;
                } else {
                    hi = mid;
                }
            }
            Ok(lo.midpoint(hi))
        };
        let (t0, t1) = if (x1 - x0).abs() < 1e-8 {
            (0.0, 1.0)
        } else if increasing {
            (root(e)?, root(e + size)?)
        } else {
            (root(e + size)?, root(e)?)
        };
        let (_, y0) = project(t0)?;
        let (_, y1) = project(t1)?;
        if y0.max(y1) > n && y0.min(y1) < n + size {
            return Ok(true);
        }
    }
    Ok(false)
}

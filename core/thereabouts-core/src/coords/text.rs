//! Bounded, non-locale text parsers. Every NMEA sentence stands alone.
use super::cartesian::geo;
use super::parse::{finite, range, syntax};
use super::{CoordError, Geodetic, NmeaFix};
fn number(s: &str, frame: &str) -> Result<f64, CoordError> {
    let x = s.parse::<f64>().map_err(|_| syntax(frame))?;
    finite(x, frame)
}
pub(super) fn geojson(values: &[f64]) -> Result<Geodetic, CoordError> {
    if !(2..=3).contains(&values.len()) {
        return Err(range("coordinates"));
    }
    let mut p = geo(values[1], values[0]);
    p.height = values.get(2).copied();
    Ok(p)
}
pub(super) fn wkt(value: &str) -> Result<Geodetic, CoordError> {
    if value.len() > 256 || !value.is_ascii() {
        return Err(syntax("wkt"));
    }
    let s = value.trim();
    let upper = s.to_ascii_uppercase();
    if [
        "SRID",
        "CRS:",
        "GEOGCS",
        "PROJCS",
        "GEODCRS",
        "GEOGCRS",
        "PROJCRS",
        "COMPD_CS",
        "COMPOUNDCRS",
        "BOUNDCRS",
        "VERT_CS",
        "VERTCRS",
        "ENGCRS",
        "LOCAL_CS",
    ]
    .iter()
    .any(|prefix| upper.starts_with(prefix))
    {
        return Err(CoordError::UnsupportedFrame {
            frame: "crs:wkt".into(),
        });
    }
    let open = s.find('(').ok_or_else(|| syntax("wkt"))?;
    let prefix = s[..open]
        .split_ascii_whitespace()
        .map(str::to_ascii_uppercase)
        .collect::<Vec<_>>();
    let dimension = if prefix == ["POINT"] {
        2
    } else if prefix == ["POINT", "Z"] {
        3
    } else {
        return Err(syntax("wkt"));
    };
    let body = s[open + 1..]
        .strip_suffix(')')
        .ok_or_else(|| syntax("wkt"))?;
    let values = body
        .split_ascii_whitespace()
        .map(|s| number(s, "wkt"))
        .collect::<Result<Vec<_>, _>>()?;
    if values.len() != dimension {
        return Err(syntax("wkt"));
    }
    geojson(&values)
}
fn axis(s: &str, negative: bool) -> Result<f64, CoordError> {
    let s = s.trim();
    if s.is_empty() {
        return Err(syntax("dms"));
    }
    let mut values = Vec::new();
    let mut chars = s.chars().peekable();
    let mut last_mark = None;
    while chars.peek().is_some() {
        while chars.peek().is_some_and(char::is_ascii_whitespace) {
            chars.next();
        }
        if chars.peek().is_none() {
            break;
        }
        if values.len() == 3 {
            return Err(syntax("dms"));
        }
        let mut token = String::new();
        while chars
            .peek()
            .is_some_and(|c| c.is_ascii_digit() || ['.', '+', '-'].contains(c))
        {
            if let Some(c) = chars.next() {
                token.push(c);
            }
        }
        if token.is_empty() {
            return Err(syntax("dms"));
        }
        if !values.is_empty() && (token.starts_with('-') || token.starts_with('+')) {
            return Err(syntax("dms"));
        }
        if values.is_empty()
            && ((token.starts_with('-') && !negative) || (token.starts_with('+') && negative))
        {
            return Err(CoordError::ConflictingFields {
                fields: vec!["sign".into(), "hemisphere".into()],
            });
        }
        let value = number(&token, "dms")?.abs();
        values.push(value);
        let whitespace = chars.peek().is_some_and(char::is_ascii_whitespace);
        while chars.peek().is_some_and(char::is_ascii_whitespace) {
            chars.next();
        }
        if let Some(c) = chars.peek().copied() {
            let mark = match c {
                '°' => Some(1),
                '\'' | '′' => Some(2),
                '"' | '″' => Some(3),
                _ => None,
            };
            if let Some(mark) = mark {
                if mark != values.len() || last_mark.is_some_and(|old| old >= mark) {
                    return Err(syntax("dms"));
                }
                last_mark = Some(mark);
                chars.next();
            } else if !whitespace {
                return Err(syntax("dms"));
            }
        }
    }
    if values.is_empty() {
        return Err(syntax("dms"));
    }
    for v in values.iter().skip(1) {
        if *v >= 60.0 {
            return Err(range("dms_minutes_seconds"));
        }
    }
    if values.len() > 1 && values[0].fract() != 0.0 {
        return Err(syntax("dms"));
    }
    if values.len() > 2 && values[1].fract() != 0.0 {
        return Err(syntax("dms"));
    }
    let angle = values[0]
        + values.get(1).copied().unwrap_or(0.0) / 60.0
        + values.get(2).copied().unwrap_or(0.0) / 3600.0;
    Ok(if negative { -angle } else { angle })
}
pub(super) fn dms(value: &str) -> Result<Geodetic, CoordError> {
    if value.len() > 256 {
        return Err(syntax("dms"));
    }
    let s = value.trim();
    let lat_end = s.find(['N', 'S']).ok_or_else(|| syntax("dms"))?;
    let lat = axis(&s[..lat_end], s.as_bytes()[lat_end] == b'S')?;
    let rest = s[lat_end + 1..].trim();
    let rest = rest.strip_prefix(',').unwrap_or(rest).trim();
    let lon_end = rest.find(['E', 'W']).ok_or_else(|| syntax("dms"))?;
    if !rest[lon_end + 1..].trim().is_empty() {
        return Err(syntax("dms"));
    }
    if !s.contains(['°', '\'', '′', '"', '″']) && !s.contains(',') {
        return Err(syntax("dms"));
    }
    let lon = axis(&rest[..lon_end], rest.as_bytes()[lon_end] == b'W')?;
    Ok(geo(lat, lon))
}
fn utc(s: &str) -> Result<Option<String>, CoordError> {
    if s.is_empty() {
        return Ok(None);
    }
    let (whole, fraction) = s.split_once('.').map_or((s, None), |(a, b)| (a, Some(b)));
    if whole.len() != 6
        || !whole.bytes().all(|c| c.is_ascii_digit())
        || fraction.is_some_and(|s| s.is_empty() || !s.bytes().all(|c| c.is_ascii_digit()))
    {
        return Err(syntax("nmea"));
    }
    let hour = whole[..2].parse::<u8>().map_err(|_| syntax("nmea"))?;
    let minute = whole[2..4].parse::<u8>().map_err(|_| syntax("nmea"))?;
    let second = whole[4..].parse::<u8>().map_err(|_| syntax("nmea"))?;
    if hour > 23 || minute > 59 || second > 60 {
        return Err(range("utc"));
    }
    Ok(Some(s.into()))
}
fn nmea_angle(s: &str, hemisphere: &str, latitude: bool) -> Result<f64, CoordError> {
    let digits = if latitude { 4 } else { 5 };
    let whole = s.split('.').next().unwrap_or("");
    if whole.len() != digits
        || !whole.bytes().all(|c| c.is_ascii_digit())
        || s.matches('.').count() > 1
        || !s.bytes().all(|c| c.is_ascii_digit() || c == b'.')
    {
        return Err(syntax("nmea"));
    }
    let degrees = number(&s[..digits - 2], "nmea")?;
    let minutes = number(&s[digits - 2..], "nmea")?;
    if !(0.0..60.0).contains(&minutes) {
        return Err(range("nmea_minutes"));
    }
    let sign = match (latitude, hemisphere) {
        (true, "N") | (false, "E") => 1.0,
        (true, "S") | (false, "W") => -1.0,
        _ => return Err(syntax("nmea")),
    };
    Ok(sign * (degrees + minutes / 60.0))
}
fn optional_number(s: &str) -> Result<Option<f64>, CoordError> {
    if s.is_empty() {
        Ok(None)
    } else {
        number(s, "nmea").map(Some)
    }
}
pub(super) fn nmea(value: &str) -> Result<(Geodetic, NmeaFix, Option<f64>), CoordError> {
    if value.len() > 1024 || !value.is_ascii() {
        return Err(syntax("nmea"));
    }
    let s = value.strip_suffix("\r\n").unwrap_or(value);
    let s = s.strip_prefix('$').ok_or(CoordError::InvalidChecksum)?;
    let (body, checksum) = s.split_once('*').ok_or(CoordError::InvalidChecksum)?;
    if checksum.len() != 2 || !checksum.bytes().all(|c| c.is_ascii_hexdigit()) {
        return Err(CoordError::InvalidChecksum);
    }
    let expected = u8::from_str_radix(checksum, 16).map_err(|_| CoordError::InvalidChecksum)?;
    if body.bytes().fold(0, |a, b| a ^ b) != expected {
        return Err(CoordError::InvalidChecksum);
    }
    let fields: Vec<_> = body.split(',').collect();
    if fields.len() > 24 || fields[0].len() != 5 {
        return Err(syntax("nmea"));
    }
    let talker = &fields[0][..2];
    let sentence = &fields[0][2..];
    if !["GP", "GN"].contains(&talker) {
        return Err(syntax("nmea"));
    }
    let (lat, ns, lon, ew, time, status, mode) = match sentence {
        "GGA" if fields.len() == 15 => (2, 3, 4, 5, 1, None, None),
        "RMC" if (12..=14).contains(&fields.len()) => (3, 4, 5, 6, 1, Some(2), fields.get(12)),
        "GLL" if (7..=8).contains(&fields.len()) => (1, 2, 3, 4, 5, Some(6), fields.get(7)),
        _ => return Err(syntax("nmea")),
    };
    if status.is_some_and(|i| fields[i] != "A") || mode.is_some_and(|s| *s == "N") {
        return Err(CoordError::NoFix);
    }
    let mut fix = NmeaFix {
        talker: talker.into(),
        sentence: sentence.into(),
        utc: utc(fields[time])?,
        quality: None,
        satellites: None,
    };
    let mut hdop = None;
    if sentence == "GGA" {
        let quality = fields[6].parse::<u8>().map_err(|_| syntax("nmea"))?;
        if quality == 0 {
            return Err(CoordError::NoFix);
        }
        if quality > 8 {
            return Err(range("quality"));
        }
        fix.quality = Some(quality);
        fix.satellites = if fields[7].is_empty() {
            None
        } else {
            let n = fields[7].parse::<u8>().map_err(|_| syntax("nmea"))?;
            if n > 99 {
                return Err(range("satellites"));
            }
            Some(n)
        };
        hdop = optional_number(fields[8])?;
        if hdop.is_some_and(|x| x < 0.0) {
            return Err(range("hdop"));
        }
    }
    if fields[lat].is_empty() || fields[lon].is_empty() {
        return Err(CoordError::NoFix);
    }
    let mut p = geo(
        nmea_angle(fields[lat], fields[ns], true)?,
        nmea_angle(fields[lon], fields[ew], false)?,
    );
    if sentence == "GGA" {
        p.height = optional_number(fields[9])?;
        p.geoid_separation = optional_number(fields[11])?;
        if (!fields[10].is_empty() && fields[10] != "M")
            || (!fields[12].is_empty() && fields[12] != "M")
            || (p.height.is_some() && fields[10] != "M")
            || (p.geoid_separation.is_some() && fields[12] != "M")
        {
            return Err(syntax("nmea"));
        }
        if p.height.is_some() {
            p.height_datum = Some("msl".into());
        }
    }
    Ok((p, fix, hdop))
}

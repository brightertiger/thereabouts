//! Strict wire parsing; only bounded text and explicitly named finite numbers.
use super::{
    CellId, CoordError, Ecef, Frame, Geodetic, Hemisphere, Origin, Point, Uncertainty, Utm,
};
use serde_json::{Map, Value};
type Object = Map<String, Value>;
pub(super) fn object<'a>(v: &'a Value, field: &str) -> Result<&'a Object, CoordError> {
    v.as_object().ok_or_else(|| invalid(field))
}
pub(super) fn invalid(field: &str) -> CoordError {
    CoordError::InvalidType {
        field: field.into(),
    }
}
pub(super) fn range(field: &str) -> CoordError {
    CoordError::OutOfRange {
        field: field.into(),
    }
}
pub(super) fn syntax(frame: &str) -> CoordError {
    CoordError::InvalidSyntax {
        frame: frame.into(),
    }
}
pub(super) fn finite(x: f64, field: &str) -> Result<f64, CoordError> {
    if x.is_finite() {
        Ok(x)
    } else {
        Err(CoordError::NonFinite {
            field: field.into(),
        })
    }
}
fn required<'a>(o: &'a Object, k: &str) -> Result<&'a Value, CoordError> {
    o.get(k)
        .ok_or_else(|| CoordError::MissingField { field: k.into() })
}
fn number(o: &Object, k: &str) -> Result<f64, CoordError> {
    finite(required(o, k)?.as_f64().ok_or_else(|| invalid(k))?, k)
}
fn optional_number(o: &Object, k: &str) -> Result<Option<f64>, CoordError> {
    if o.get(k).is_none_or(Value::is_null) {
        Ok(None)
    } else {
        number(o, k).map(Some)
    }
}
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str, CoordError> {
    let s = v.as_str().ok_or_else(|| invalid(k))?;
    if s.len() > 1024 {
        return Err(range(k));
    }
    Ok(s)
}
fn optional_text(o: &Object, k: &str) -> Result<Option<String>, CoordError> {
    o.get(k)
        .filter(|v| !v.is_null())
        .map(|v| text(v, k).map(str::to_owned))
        .transpose()
}
fn keys(o: &Object, allowed: &[&str]) -> Result<(), CoordError> {
    let extra: Vec<_> = o
        .keys()
        .filter(|k| !allowed.contains(&k.as_str()))
        .take(16)
        .map(|k| k.chars().take(64).collect())
        .collect();
    if extra.is_empty() {
        Ok(())
    } else {
        Err(CoordError::ConflictingFields { fields: extra })
    }
}
fn geodetic(o: &Object) -> Result<Geodetic, CoordError> {
    Ok(Geodetic {
        lat: number(o, "lat")?,
        lon: number(o, "lon")?,
        height: optional_number(o, "height")?,
        height_datum: optional_text(o, "height_datum")?,
        geoid_separation: optional_number(o, "geoid_separation")?,
    })
}
fn ecef(o: &Object) -> Result<Ecef, CoordError> {
    Ok(Ecef {
        x: number(o, "x")?,
        y: number(o, "y")?,
        z: number(o, "z")?,
    })
}
fn label(o: &Object) -> Result<&str, CoordError> {
    o.get("frame")
        .filter(|v| !v.is_null())
        .map_or(Ok("geodetic"), |v| text(v, "frame"))
}
fn origin(o: &Object) -> Result<Origin, CoordError> {
    let v = o
        .get("origin")
        .filter(|v| !v.is_null())
        .ok_or(CoordError::MissingOrigin)?;
    let o = object(v, "origin")?;
    match label(o)? {
        "geodetic" | "latlon" | "lla" | "llh" => {
            keys(
                o,
                &[
                    "frame",
                    "lat",
                    "lon",
                    "height",
                    "height_datum",
                    "geoid_separation",
                ],
            )?;
            Ok(Origin::Geodetic(geodetic(o)?))
        }
        "ecef" => {
            keys(o, &["frame", "x", "y", "z"])?;
            Ok(Origin::Ecef(ecef(o)?))
        }
        _ => Err(invalid("origin.frame")),
    }
}
fn cell(o: &Object) -> Result<CellId, CoordError> {
    let v = required(o, "cell")?;
    if let Some(n) = v.as_u64() {
        return Ok(CellId::Integer(n));
    }
    Ok(CellId::Text(text(v, "cell")?.into()))
}
/// Parse one strict tagged component object and validate its full native domain.
/// Unknown keys, numeric strings, bools, origin recursion and nonfinite numbers fail.
#[allow(clippy::too_many_lines)] // Explicit dispatch keeps the wire schema in one place.
pub fn parse_point(value: &Value) -> Result<Point, CoordError> {
    let o = object(value, "point")?;
    let frame = label(o)?;
    let fields: &[&str] = match frame {
        "geodetic" | "latlon" | "lla" | "llh" => {
            &["lat", "lon", "height", "height_datum", "geoid_separation"]
        }
        "ecef" => &["x", "y", "z"],
        "enu" => &["e", "n", "u", "origin"],
        "ned" => &["n", "e", "d", "origin"],
        "utm" => &["zone", "hemisphere", "band", "easting", "northing"],
        "mgrs" | "geohash" | "dms" | "nmea" | "wkt" => &["value"],
        "pluscode" => &["value", "reference"],
        "h3" | "s2" => &["cell"],
        "geojson" => &["coordinates", "type"],
        _ => {
            return Err(CoordError::UnsupportedFrame {
                frame: frame.into(),
            });
        }
    };
    let allowed: Vec<_> = fields
        .iter()
        .copied()
        .chain(["frame", "uncertainty"])
        .collect();
    keys(o, &allowed)?;
    let frame = match frame {
        "geodetic" | "latlon" | "lla" | "llh" => Frame::Geodetic(geodetic(o)?),
        "ecef" => Frame::Ecef(ecef(o)?),
        "enu" => Frame::Enu {
            e: number(o, "e")?,
            n: number(o, "n")?,
            u: number(o, "u")?,
            origin: origin(o)?,
        },
        "ned" => Frame::Ned {
            n: number(o, "n")?,
            e: number(o, "e")?,
            d: number(o, "d")?,
            origin: origin(o)?,
        },
        "utm" => {
            let zone = required(o, "zone")?
                .as_u64()
                .and_then(|x| u8::try_from(x).ok())
                .ok_or_else(|| invalid("zone"))?;
            let hemisphere = match optional_text(o, "hemisphere")?.as_deref() {
                None => None,
                Some("N") => Some(Hemisphere::North),
                Some("S") => Some(Hemisphere::South),
                _ => return Err(range("hemisphere")),
            };
            let band = optional_text(o, "band")?
                .map(|s| {
                    if s.len() == 1 {
                        s.chars().next().ok_or_else(|| invalid("band"))
                    } else {
                        Err(invalid("band"))
                    }
                })
                .transpose()?;
            Frame::Utm(Utm {
                zone,
                hemisphere,
                band,
                easting: number(o, "easting")?,
                northing: number(o, "northing")?,
            })
        }
        "h3" => Frame::H3(cell(o)?),
        "s2" => Frame::S2(cell(o)?),
        "geojson" => {
            if let Some(kind) = o.get("type").filter(|v| !v.is_null())
                && text(kind, "type")? != "Point"
            {
                return Err(syntax("geojson"));
            }
            let a = required(o, "coordinates")?
                .as_array()
                .ok_or_else(|| invalid("coordinates"))?;
            if !(2..=3).contains(&a.len()) {
                return Err(range("coordinates"));
            }
            Frame::GeoJson(
                a.iter()
                    .map(|x| x.as_f64().ok_or_else(|| invalid("coordinates")))
                    .collect::<Result<_, _>>()?,
            )
        }
        "pluscode" => {
            let reference = o
                .get("reference")
                .filter(|v| !v.is_null())
                .map(|v| {
                    let r = object(v, "reference")?;
                    keys(
                        r,
                        &["lat", "lon", "height", "height_datum", "geoid_separation"],
                    )?;
                    geodetic(r)
                })
                .transpose()?;
            Frame::Pluscode {
                value: text(required(o, "value")?, "value")?.into(),
                reference,
            }
        }
        label => {
            let s = text(required(o, "value")?, "value")?.into();
            match label {
                "mgrs" => Frame::Mgrs(s),
                "geohash" => Frame::Geohash(s),
                "dms" => Frame::Dms(s),
                "nmea" => Frame::Nmea(s),
                "wkt" => Frame::Wkt(s),
                _ => return Err(syntax(label)),
            }
        }
    };
    let uncertainty = if let Some(v) = o.get("uncertainty").filter(|v| !v.is_null()) {
        let u = object(v, "uncertainty")?;
        keys(u, &["accuracy_m", "hdop", "vdop"])?;
        Uncertainty {
            accuracy_m: optional_number(u, "accuracy_m")?,
            hdop: optional_number(u, "hdop")?,
            vdop: optional_number(u, "vdop")?,
        }
    } else {
        Uncertainty::default()
    };
    let point = Point { frame, uncertainty };
    super::normalize(&point)?;
    Ok(point)
}

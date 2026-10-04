//! Coordinate CLI assembly and column binding. Geographic validation lives in core.
use crate::error::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use thereabouts_core::coords::{self, CoordError};

/// Serde-defaulted batch options shared by native and WASM hosts.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Options {
    /// Explicit uniform frame; absence preserves legacy recognition.
    pub frame: Option<String>,
    /// Input encoding, independent of output encoding. Empty means auto.
    pub input_format: String,
    /// Uniform local origin or plus-code reference and UTM/uncertainty values.
    pub defaults: Map<String, Value>,
    /// Coordinate component to explicitly selected CSV header.
    pub columns: BTreeMap<String, String>,
}
const COMPONENTS: &[&str] = &[
    "lat",
    "lon",
    "height",
    "height_datum",
    "geoid_separation",
    "x",
    "y",
    "z",
    "e",
    "n",
    "u",
    "d",
    "origin",
    "zone",
    "hemisphere",
    "band",
    "easting",
    "northing",
    "value",
    "cell",
    "reference",
    "coordinates",
    "type",
    "uncertainty",
];
const META: &[&str] = &["accuracy_m", "hdop", "vdop"];
const NUMERIC: &[&str] = &[
    "lat",
    "lon",
    "height",
    "geoid_separation",
    "x",
    "y",
    "z",
    "e",
    "n",
    "u",
    "d",
    "zone",
    "easting",
    "northing",
    "accuracy_m",
    "hdop",
    "vdop",
];
/// Canonical labels are used only for syntax conflicts, never for conversion.
#[must_use]
pub fn canonical(frame: &str) -> &str {
    match frame {
        "latlon" | "lla" | "llh" => "geodetic",
        other => other,
    }
}
fn supported(frame: &str) -> bool {
    matches!(
        canonical(frame),
        "geodetic"
            | "ecef"
            | "enu"
            | "ned"
            | "utm"
            | "mgrs"
            | "geohash"
            | "pluscode"
            | "h3"
            | "s2"
            | "dms"
            | "nmea"
            | "geojson"
            | "wkt"
    )
}
fn usage(message: impl Into<String>) -> Error {
    Error::Usage(message.into())
}
fn json_object(text: &str, flag: &str) -> Result<Value> {
    let value: Value =
        serde_json::from_str(text).map_err(|e| usage(format!("Invalid --{flag} JSON: {e}")))?;
    if !value.is_object() {
        return Err(usage(format!("--{flag} requires a JSON object")));
    }
    Ok(value)
}
fn number(text: &str) -> Value {
    // Invalid CSV numbers remain strings so core emits an InvalidType, not a pack error.
    if let Ok(integer) = text.parse::<i64>() {
        return Value::from(integer);
    }
    text.parse::<f64>()
        .ok()
        .and_then(serde_json::Number::from_f64)
        .map_or_else(|| Value::String(text.into()), Value::Number)
}
fn nonfinite(text: &str, field: &str) -> Option<CoordError> {
    text.parse::<f64>()
        .ok()
        .filter(|number| serde_json::Number::from_f64(*number).is_none())
        .map(|_| CoordError::NonFinite {
            field: field.into(),
        })
}
/// JSON cannot carry IEEE nonfinite numbers; preserve their core diagnostic before serialization.
pub fn scalar_error(flags: &Map<String, Value>) -> Result<Option<Value>> {
    let Some(frame) = flags.get("frame").and_then(Value::as_str) else {
        return Ok(None);
    };
    for (flag, value) in flags {
        let key = flag.replace('-', "_");
        if NUMERIC.contains(&key.as_str())
            && let Some(error) = value
                .as_str()
                .and_then(|v| nonfinite(v, mapped(frame, &key)))
        {
            return Ok(Some(serde_json::to_value(coords::invalid_result(
                Some(frame),
                &error,
            ))?));
        }
    }
    Ok(None)
}
fn default_issue(defaults: &Map<String, Value>) -> Option<CoordError> {
    for (key, value) in defaults {
        if key == "uncertainty" {
            for (field, value) in value.as_object().into_iter().flatten() {
                if let Some(error) = value.as_str().and_then(|v| nonfinite(v, field)) {
                    return Some(error);
                }
            }
        } else if NUMERIC.contains(&key.as_str())
            && let Some(error) = value.as_str().and_then(|v| nonfinite(v, key))
        {
            return Some(error);
        }
    }
    None
}
fn allowed(frame: &str) -> &'static [&'static str] {
    match canonical(frame) {
        "geodetic" => &["lat", "lon", "height", "height_datum", "geoid_separation"],
        "ecef" => &["x", "y", "z"],
        "enu" => &["e", "n", "u", "origin"],
        "ned" => &["n", "e", "d", "origin"],
        "utm" => &["zone", "hemisphere", "band", "easting", "northing"],
        "pluscode" => &["value", "reference"],
        "h3" | "s2" => &["cell"],
        "geojson" => &["coordinates", "type"],
        _ => &["value"],
    }
}
fn mapped<'a>(frame: &str, flag: &'a str) -> &'a str {
    match (canonical(frame), flag) {
        ("enu", "x") | ("ned", "y") => "e",
        ("enu", "y") | ("ned", "x") => "n",
        ("enu", "z") => "u",
        ("ned", "z") => "d",
        ("h3" | "s2", "value") => "cell",
        (_, "accuracy") => "accuracy_m",
        _ => flag,
    }
}
fn required(frame: &str) -> &'static [&'static str] {
    match canonical(frame) {
        "geodetic" => &["lat", "lon"],
        "ecef" => &["x", "y", "z"],
        "enu" => &["e", "n", "u"],
        "ned" => &["n", "e", "d"],
        "utm" => &["zone", "easting", "northing"],
        "geojson" => &["coordinates"],
        "h3" | "s2" => &["cell"],
        _ => &["value"],
    }
}
/// Validate command syntax and assemble wire input without doing coordinate maths.
pub fn request(
    flags: &Map<String, Value>,
    filenames: &[String],
) -> Result<(Option<Value>, Options)> {
    let files = filenames.len();
    let has = |key: &str| flags.contains_key(key);
    let text = |key: &str| flags.get(key).and_then(Value::as_str);
    let mut options = Options {
        frame: text("frame").map(str::to_owned),
        input_format: text("input-format").unwrap_or("auto").into(),
        ..Options::default()
    };
    if matches!(options.input_format.as_str(), "auto" | "")
        && filenames.first().is_some_and(|f| {
            std::path::Path::new(f).extension().is_some_and(|e| {
                e.eq_ignore_ascii_case("ndjson") || e.eq_ignore_ascii_case("jsonl")
            })
        })
        && flags.keys().any(|k| k.ends_with("-col"))
    {
        return Err(usage("Column flags apply only to CSV input"));
    }
    if files > 1 {
        return Err(usage("Use one FILE, --point JSON, or scalar components"));
    }
    if let Some(point) = text("point") {
        if files > 0 || flags.keys().any(|k| is_coordinate_flag(k) && k != "point") {
            return Err(usage(
                "--point cannot be combined with FILE, --frame, components or metadata",
            ));
        }
        let value = json_object(point, "point")?;
        if !value.get("frame").is_some_and(Value::is_string) {
            return Err(usage(
                "--point must contain its frame; use a complete typed object",
            ));
        }
        return Ok((Some(value), options));
    }
    if files == 0 && (has("input-format") || flags.keys().any(|k| k.ends_with("-col"))) {
        return Err(usage("Input format and column flags require a FILE"));
    }
    if options.frame.is_none() {
        if flags.keys().any(|k| {
            is_coordinate_flag(k)
                && !matches!(
                    k.as_str(),
                    "lat" | "lon" | "lat-col" | "lon-col" | "input-format"
                )
        }) {
            return Err(usage(
                "Coordinate components and metadata require explicit --frame or --point",
            ));
        }
        if files == 0 && (!has("lat") || !has("lon")) {
            return Err(usage("reverse requires both --lat and --lon, or a FILE"));
        }
        if files > 0 && (has("lat") || has("lon")) {
            return Err(usage("FILE and scalar components are mutually exclusive"));
        }
        if options.input_format == "nmea" {
            return Err(usage("--input-format nmea requires --frame nmea"));
        }
        options.validate_columns(flags)?;
        return Ok((None, options));
    }
    let frame = options.frame.clone().unwrap_or_default();
    if !supported(&frame) {
        return Err(usage(CoordError::UnsupportedFrame { frame }.to_string()));
    }
    if options.input_format == "csv" && canonical(&frame) == "geojson" {
        return Err(usage(
            "Use --point JSON or NDJSON for GeoJSON arrays; frame geojson cannot read CSV",
        ));
    }
    if options.input_format == "nmea" && canonical(&frame) != "nmea" {
        return Err(usage("--input-format nmea requires --frame nmea"));
    }
    if matches!(canonical(&frame), "enu" | "ned")
        && !has("origin")
        && (files == 0 || options.input_format == "csv")
    {
        return Err(usage(CoordError::MissingOrigin.to_string()));
    }
    let mut point = components(flags, files, &frame)?;
    options.validate_columns(flags)?;
    if files == 0 {
        if canonical(&frame) == "geojson" {
            return Err(usage("Use --point JSON or NDJSON for GeoJSON arrays"));
        }
        for key in required(&frame) {
            if !point.contains_key(*key) {
                return Err(usage(format!("Frame {frame} requires {key}")));
            }
        }
        if canonical(&frame) == "utm" && !has("hemisphere") && !has("band") {
            return Err(usage("Frame utm requires --hemisphere or --band"));
        }
        Ok((Some(Value::Object(point)), options))
    } else {
        point.remove("frame");
        options.defaults = point;
        Ok((None, options))
    }
}
fn components(flags: &Map<String, Value>, files: usize, frame: &str) -> Result<Map<String, Value>> {
    let mut point = Map::from_iter([("frame".into(), Value::String(frame.into()))]);
    let mut uncertainty = Map::new();
    for (flag, value) in flags {
        if !is_coordinate_flag(flag)
            || matches!(flag.as_str(), "frame" | "input-format")
            || flag.ends_with("-col")
        {
            continue;
        }
        let key = flag.replace('-', "_");
        let key = mapped(frame, &key);
        if !allowed(frame).contains(&key) && !META.contains(&key) {
            return Err(usage(format!("--{flag} is not valid for frame {frame}")));
        }
        let raw = value.as_str().unwrap_or_default();
        let value = if matches!(key, "origin" | "reference") {
            json_object(raw, flag)?
        } else if NUMERIC.contains(&key) {
            number(raw)
        } else {
            value.clone()
        };
        if META.contains(&key) {
            uncertainty.insert(key.into(), value);
        } else {
            point.insert(key.into(), value);
        }
        if files > 0
            && !matches!(
                key,
                "origin"
                    | "reference"
                    | "zone"
                    | "hemisphere"
                    | "band"
                    | "accuracy_m"
                    | "hdop"
                    | "vdop"
            )
        {
            return Err(usage("FILE and scalar components are mutually exclusive"));
        }
    }
    if !uncertainty.is_empty() {
        point.insert("uncertainty".into(), Value::Object(uncertainty));
    }
    Ok(point)
}
fn is_coordinate_flag(flag: &str) -> bool {
    let key = flag.trim_end_matches("-col").replace('-', "_");
    COMPONENTS.contains(&key.as_str())
        || META.contains(&key.as_str())
        || matches!(
            key.as_str(),
            "frame" | "point" | "input_format" | "accuracy"
        )
}
impl Options {
    fn validate_columns(&mut self, flags: &Map<String, Value>) -> Result<()> {
        for (flag, value) in flags.iter().filter(|(k, _)| k.ends_with("-col")) {
            if !matches!(self.input_format.as_str(), "auto" | "csv" | "") {
                return Err(usage("Column flags apply only to CSV input"));
            }
            let name = flag.trim_end_matches("-col").replace('-', "_");
            let frame = self.frame.as_deref().unwrap_or("geodetic");
            let key = mapped(frame, &name);
            if !allowed(frame).contains(&key) && !META.contains(&key) {
                return Err(usage(format!("--{flag} is not valid for frame {frame}")));
            }
            let header = value.as_str().unwrap_or_default().to_owned();
            if self.columns.values().any(|v| v == &header) {
                return Err(usage(
                    "Two coordinate components cannot bind the same CSV column",
                ));
            }
            if flags.contains_key(name.replace('_', "-").as_str())
                || key == "accuracy_m" && flags.contains_key("accuracy-m")
            {
                return Err(usage(format!("Uniform {key} conflicts with --{flag}")));
            }
            self.columns.insert(key.into(), header);
        }
        Ok(())
    }
    /// Extract only coordinate components, retaining other record keys in the output.
    pub fn record(
        &self,
        input: &Map<String, Value>,
    ) -> std::result::Result<Option<Value>, CoordError> {
        if !input.contains_key("frame") && self.frame.is_none() {
            return Ok(None);
        }
        if let Some(error) = default_issue(&self.defaults) {
            return Err(error);
        }
        let mut point: Map<String, Value> = input
            .iter()
            .filter(|(k, _)| {
                COMPONENTS.contains(&k.as_str())
                    || META.contains(&k.as_str())
                    || k.as_str() == "frame"
            })
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        if let Some(frame) = &self.frame {
            if let Some(declared) = point.get("frame") {
                if declared
                    .as_str()
                    .is_none_or(|v| canonical(v) != canonical(frame))
                {
                    return Err(CoordError::ConflictingFields {
                        fields: vec!["frame".into()],
                    });
                }
            } else {
                point.insert("frame".into(), Value::String(frame.clone()));
            }
        }
        for (key, value) in &self.defaults {
            if key == "uncertainty"
                && let Some(row) = point.get_mut(key).and_then(Value::as_object_mut)
            {
                for (field, default) in value.as_object().into_iter().flatten() {
                    if row
                        .get(field)
                        .filter(|v| !v.is_null())
                        .is_some_and(|v| !same_number_or_value(v, default))
                    {
                        return Err(CoordError::ConflictingFields {
                            fields: vec![format!("uncertainty.{field}")],
                        });
                    }
                    row.entry(field.clone())
                        .and_modify(|v| {
                            if v.is_null() {
                                *v = default.clone();
                            }
                        })
                        .or_insert_with(|| default.clone());
                }
                continue;
            }
            if let Some(row) = point.get(key).filter(|v| !v.is_null()) {
                if !context_equal(key, row, value)? {
                    return Err(CoordError::ConflictingFields {
                        fields: vec![key.clone()],
                    });
                }
            } else {
                point.insert(key.clone(), value.clone());
            }
        }
        Ok(Some(Value::Object(point)))
    }
    /// Bind frame CSV headers once, before processing any rows.
    pub fn bind(&self, headers: &csv::StringRecord) -> Result<Columns> {
        let frame = self.frame.as_deref().unwrap_or("geodetic");
        if canonical(frame) == "geojson" {
            return Err(usage(
                "Use --point JSON or NDJSON for GeoJSON arrays; frame geojson cannot read CSV",
            ));
        }
        if matches!(canonical(frame), "enu" | "ned") && !self.defaults.contains_key("origin") {
            return Err(usage(CoordError::MissingOrigin.to_string()));
        }
        let mut columns = Vec::new();
        let mut used = BTreeSet::new();
        for key in allowed(frame)
            .iter()
            .copied()
            .filter(|k| !matches!(*k, "origin" | "reference" | "type"))
            .chain(META.iter().copied())
        {
            let explicit = self.columns.get(key);
            let aliases: &[&str] = match key {
                "lat" => &["lat", "latitude"],
                "lon" => &["lon", "longitude", "lng"],
                _ => &[key],
            };
            let found: Vec<_> = headers
                .iter()
                .enumerate()
                .filter(|(_, h)| explicit.map_or_else(|| aliases.contains(h), |e| *h == e))
                .map(|(i, _)| i)
                .collect();
            let uniform = if META.contains(&key) {
                self.defaults.get("uncertainty").and_then(|v| v.get(key))
            } else {
                self.defaults.get(key)
            };
            if uniform.is_some() && !found.is_empty() {
                return Err(usage(format!(
                    "Uniform {key} conflicts with CSV column {key}"
                )));
            }
            if found.len() > 1
                || found.is_empty()
                    && (explicit.is_some() || required(frame).contains(&key) && uniform.is_none())
            {
                return Err(usage(format!(
                    "CSV coordinate header {key} is absent or ambiguous; select its --*-col override"
                )));
            }
            if let Some(index) = found.first() {
                if !used.insert(*index) {
                    return Err(usage(
                        "Two coordinate components cannot bind the same CSV column",
                    ));
                }
                columns.push((key.to_owned(), *index));
            }
        }
        if canonical(frame) == "utm"
            && !["hemisphere", "band"].iter().any(|k| {
                self.defaults.contains_key(*k) || columns.iter().any(|(name, _)| name == k)
            })
        {
            return Err(usage("CSV frame utm requires hemisphere or band"));
        }
        Ok(Columns {
            frame: frame.into(),
            fields: columns,
            defaults: self.defaults.clone(),
        })
    }
}
fn same_number_or_value(left: &Value, right: &Value) -> bool {
    left == right
        || left
            .as_f64()
            .zip(right.as_f64())
            .is_some_and(|(a, b)| a.partial_cmp(&b) == Some(std::cmp::Ordering::Equal))
}
fn context_equal(key: &str, left: &Value, right: &Value) -> std::result::Result<bool, CoordError> {
    if !matches!(key, "origin" | "reference") {
        return Ok(same_number_or_value(left, right));
    }
    let normalize = |value: &Value| -> std::result::Result<_, CoordError> {
        let mut value = if key == "origin" {
            serde_json::json!({"frame":"enu", "e":0, "n":0, "u":0, "origin":value})
        } else {
            value.clone()
        };
        if let Some(object) = value.as_object_mut() {
            object
                .entry("frame")
                .or_insert(Value::String("geodetic".into()));
        }
        Ok(coords::normalize(&coords::parse_point(&value)?)?.point)
    };
    Ok(normalize(left)? == normalize(right)?)
}
/// Resolved CSV dimensions; raw records are never rewritten.
pub struct Columns {
    frame: String,
    fields: Vec<(String, usize)>,
    defaults: Map<String, Value>,
}
impl Columns {
    /// Coerce CSV strings once in Rust; invalid numbers stay invalid wire types.
    pub fn point(&self, record: &csv::StringRecord) -> std::result::Result<Value, CoordError> {
        if let Some(error) = default_issue(&self.defaults) {
            return Err(error);
        }
        let mut point = self.defaults.clone();
        point.insert("frame".into(), Value::String(self.frame.clone()));
        let mut uncertainty = point
            .remove("uncertainty")
            .and_then(|v| v.as_object().cloned())
            .unwrap_or_default();
        for (key, index) in &self.fields {
            let raw = record.get(*index).unwrap_or("");
            if NUMERIC.contains(&key.as_str())
                && let Some(error) = nonfinite(raw, key)
            {
                return Err(error);
            }
            let value = if raw.is_empty() && !required(&self.frame).contains(&key.as_str()) {
                Value::Null
            } else if NUMERIC.contains(&key.as_str()) {
                number(raw)
            } else {
                Value::String(raw.into())
            };
            if META.contains(&key.as_str()) {
                uncertainty.insert(key.clone(), value);
            } else {
                point.insert(key.clone(), value);
            }
        }
        if !uncertainty.is_empty() {
            point.insert("uncertainty".into(), Value::Object(uncertainty));
        }
        Ok(Value::Object(point))
    }
}

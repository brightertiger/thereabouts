//! Coordinate JSON failures are public invalid-input results, never pack errors.
use thereabouts_core::{
    coords::{self, CoordError, PointResult},
    format::Pack,
};
use wasm_bindgen::JsValue;

/// Restore coordinate metadata numbers with the host's correctly rounded JSON
/// parser. `serde_json`'s default decimal parser can lose a bit on wasm32, even
/// for exact binary geohash bounds. Keep legacy result parsing byte-compatible.
pub(crate) fn restore_metadata(
    value: &mut serde_json::Value,
    source: &JsValue,
) -> Result<(), JsValue> {
    match value {
        serde_json::Value::Number(number) if number.is_f64() => {
            if let Some(number) = source.as_f64().and_then(serde_json::Number::from_f64) {
                *value = serde_json::Value::Number(number);
            }
        }
        serde_json::Value::Object(fields) => {
            for (key, value) in fields {
                restore_metadata(value, &js_sys::Reflect::get(source, &key.as_str().into())?)?;
            }
        }
        serde_json::Value::Array(values) => {
            for (index, value) in values.iter_mut().enumerate() {
                restore_metadata(
                    value,
                    &js_sys::Reflect::get(source, &index.to_string().into())?,
                )?;
            }
        }
        _ => {}
    }
    Ok(())
}

pub(crate) fn reverse(
    pack: &Pack,
    request: &str,
    evidence: bool,
) -> thereabouts_core::Result<PointResult> {
    match serde_json::from_str(request) {
        Ok(value) => coords::reverse_value(pack, &value, evidence),
        Err(_) => Ok(coords::invalid_result(
            None,
            &CoordError::InvalidSyntax {
                frame: "json".into(),
            },
        )),
    }
}

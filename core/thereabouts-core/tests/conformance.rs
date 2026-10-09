//! The same `snake_case` fixtures run through Rust, Python and later Node.
#![cfg_attr(
    test,
    allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)
)]
use serde_json::Value;
use std::{collections::BTreeSet, fs, path::PathBuf};
use thereabouts_core::format::Pack;
fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures")
}
/// Coordinates come from libm trigonometry, whose last bit differs between `x86_64`
/// and ARM; they match within 1e-9 degrees. Every other value is exact.
const COORDINATE_TOLERANCE: f64 = 1e-9;
fn close(actual: &Value, expected: &Value, key: &str) {
    match (actual, expected) {
        (Value::Number(a), Value::Number(b)) if matches!(key, "lat" | "lon") => assert!(
            (a.as_f64().unwrap() - b.as_f64().unwrap()).abs() <= COORDINATE_TOLERANCE,
            "{key}: {actual} != {expected}"
        ),
        (Value::Object(a), Value::Object(b)) => {
            assert_eq!(
                a.keys().collect::<BTreeSet<_>>(),
                b.keys().collect::<BTreeSet<_>>()
            );
            for (key, value) in a {
                close(value, &b[key], key);
            }
        }
        (Value::Array(a), Value::Array(b)) => {
            assert_eq!(a.len(), b.len());
            for (a, b) in a.iter().zip(b) {
                close(a, b, key);
            }
        }
        _ => assert_eq!(actual, expected, "{key}"),
    }
}
fn run(bundle: &str) {
    let root = fixtures();
    let value: Value = serde_json::from_slice(&fs::read(root.join(bundle)).unwrap()).unwrap();
    let pack = Pack::open(&root.join(value["pack"].as_str().unwrap()), false).unwrap();
    for case in value["cases"].as_array().unwrap() {
        let request = &case["request"];
        let values = &request["values"];
        let result = if request["kind"] == "h3" {
            pack.from_h3(values[0].as_str().unwrap_or(""), false)
                .unwrap()
        } else if let (Some(lat), Some(lon)) = (values[0].as_f64(), values[1].as_f64()) {
            pack.reverse(lat, lon, false).unwrap()
        } else {
            pack.reverse(f64::NAN, 0.0, false).unwrap()
        };
        close(&serde_json::to_value(result).unwrap(), &case["result"], "");
    }
}
#[test]
fn synthetic_reverse_vectors() {
    run("core-synthetic-vectors.json");
}
#[test]
fn real_reverse_vectors() {
    run("core-sample-vectors.json");
}

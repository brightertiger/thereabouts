//! Shared phone vectors include nested prefixes and shared calling codes.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
mod support;
use std::{fs, path::PathBuf};
#[test]
fn phone_vectors() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures");
    for name in ["phone-vectors.json", "phone-synthetic-vectors.json"] {
        let bundle: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join(name)).unwrap()).unwrap();
        let pack = support::pack(&root.join(bundle["pack"].as_str().unwrap()), true);
        for case in bundle["cases"].as_array().unwrap() {
            let r = &case["request"];
            let answer = pack
                .phone(r["values"][0].as_str().unwrap_or(""), false)
                .unwrap();
            assert_eq!(
                serde_json::to_value(answer).unwrap(),
                case["result"],
                "{}",
                case["id"]
            );
        }
    }
}

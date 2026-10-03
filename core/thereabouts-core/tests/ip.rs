//! Shared IP vectors cover both address families and inclusive endpoints.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
use std::{fs, path::PathBuf};
use thereabouts_core::format::Pack;
#[test]
fn ip_vectors() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures");
    for name in ["ip-vectors.json"] {
        let bundle: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join(name)).unwrap()).unwrap();
        let pack = Pack::open(&root.join(bundle["pack"].as_str().unwrap()), true).unwrap();
        for case in bundle["cases"].as_array().unwrap() {
            let r = &case["request"];
            let answer = pack
                .ip(r["values"][0].as_str().unwrap_or(""), false)
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

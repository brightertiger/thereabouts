//! Original airport expectations remain the oracle; only the default scheme rule changes.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
use std::{fs, path::PathBuf};
use thereabouts_core::format::Pack;
#[test]
fn plate_vectors() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures");
    for name in ["plates-vectors.json"] {
        let bundle: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join(name)).unwrap()).unwrap();
        let pack = Pack::open(&root.join(bundle["pack"].as_str().unwrap()), true).unwrap();
        for case in bundle["cases"].as_array().unwrap() {
            let r = &case["request"];
            let answer = pack
                .plate(
                    r["values"][0].as_str().unwrap_or(""),
                    r["country"].as_str(),
                    r["series"].as_str(),
                    false,
                )
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

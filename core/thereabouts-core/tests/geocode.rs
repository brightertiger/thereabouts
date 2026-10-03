//! Shared city-name vectors, including explicit synthetic English and alternate spellings.
#![allow(clippy::unwrap_used, clippy::indexing_slicing)]
use std::{fs, path::PathBuf};
use thereabouts_core::{format::Pack, geocode::Options};
#[test]
fn geocode_vectors() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures");
    for name in ["geocode-vectors.json", "geocode-synthetic-vectors.json"] {
        let bundle: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join(name)).unwrap()).unwrap();
        let pack = Pack::open(&root.join(bundle["pack"].as_str().unwrap()), true).unwrap();
        for case in bundle["cases"].as_array().unwrap() {
            let r = &case["request"];
            let options = Options {
                country: r["country"].as_str(),
                subdivision: r["subdivision"].as_str(),
                prefer: r["prefer"].as_str(),
                scope: r["scope"].as_str().unwrap_or("cities"),
                limit: usize::try_from(r["limit"].as_u64().unwrap_or(5)).unwrap(),
                evidence: false,
            };
            let answer = pack
                .geocode(r["values"][0].as_str().unwrap_or(""), options)
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

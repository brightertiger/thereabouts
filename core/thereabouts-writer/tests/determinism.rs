//! Export determinism uses the committed synthetic dataset.
#![cfg_attr(
    test,
    allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)
)]
use std::{fs, path::PathBuf};
use thereabouts_core::format::verify;
use thereabouts_writer::{self as writer, Options};
fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures")
}
#[test]
fn parquet_writer_is_deterministic_and_idempotent() {
    let root = fixtures();
    let temp = tempfile::tempdir().unwrap();
    let output = temp.path().join("pack");
    let original = verify::verify(&root.join("packs/core-synthetic")).unwrap();
    let options: Options = serde_json::from_value(original.inputs["options"].clone()).unwrap();
    let first = writer::write_pack(
        &root.join("datasets/core-synthetic/golden"),
        "core",
        &output,
        &options,
    )
    .unwrap();
    assert_eq!(first.input_digest, original.input_digest);
    assert_eq!(
        serde_json::to_value(&first).unwrap(),
        serde_json::to_value(&original).unwrap()
    );
    let before = fs::metadata(output.join("manifest.json"))
        .unwrap()
        .modified()
        .unwrap();
    writer::write_pack(
        &root.join("datasets/core-synthetic/golden"),
        "core",
        &output,
        &options,
    )
    .unwrap();
    assert_eq!(
        before,
        fs::metadata(output.join("manifest.json"))
            .unwrap()
            .modified()
            .unwrap()
    );
}

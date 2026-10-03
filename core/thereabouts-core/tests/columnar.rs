//! Evidence payloads are cold, while default lookups and explicit verification differ deliberately.
#![allow(clippy::unwrap_used, clippy::indexing_slicing)]
use std::{fs, path::PathBuf};
use thereabouts_core::format::{Pack, manifest, verify};
#[test]
fn cold_evidence_is_not_read_by_default_queries() {
    let source = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/packs/postal-synthetic");
    let temp = tempfile::tempdir().unwrap();
    for entry in fs::read_dir(&source).unwrap() {
        let path = entry.unwrap().path();
        fs::copy(&path, temp.path().join(path.file_name().unwrap())).unwrap();
    }
    let path = temp.path().join("evidence_strings-00000.bin");
    let mut bytes = fs::read(&path).unwrap();
    let offset = usize::try_from(u64::from_le_bytes(bytes[72..80].try_into().unwrap())).unwrap();
    bytes[offset..].fill(0);
    fs::write(path, bytes).unwrap();
    let pack = Pack::open(temp.path(), false).unwrap();
    assert_eq!(
        pack.postal("00100", Some("AA"), false)
            .unwrap()
            .status
            .as_str(),
        "matched"
    );
    assert!(pack.postal("00100", Some("AA"), true).is_err());
    assert!(verify::verify(temp.path()).is_err());
}
#[test]
fn forward_minor_zero_is_explicitly_incompatible() {
    let source = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/packs/postal-synthetic");
    let temp = tempfile::tempdir().unwrap();
    let mut value: serde_json::Value =
        serde_json::from_slice(&fs::read(source.join("manifest.json")).unwrap()).unwrap();
    value["format_minor"] = 0.into();
    fs::write(
        temp.path().join("manifest.json"),
        serde_json::to_vec(&value).unwrap(),
    )
    .unwrap();
    let error = manifest::read(temp.path()).unwrap_err();
    assert!(matches!(error, thereabouts_core::Error::Incompatible(_)));
}

//! Shard grouping changes only the file layout, never an answer.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
use std::path::PathBuf;
use thereabouts_core::format::{Pack, manifest::Manifest, verify};
use thereabouts_writer::{self as writer, Options};

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures")
}
fn kinds(manifest: &Manifest, kind: &str) -> usize {
    manifest.files.iter().filter(|f| f.kind == kind).count()
}
#[test]
fn blocks_and_places_share_shards_up_to_the_target() {
    let root = fixtures();
    let dataset = root.join("datasets/core-synthetic/golden");
    let original = verify::verify(&root.join("packs/core-synthetic")).unwrap();
    let options: Options = serde_json::from_value(original.inputs["options"].clone()).unwrap();
    let temp = tempfile::tempdir().unwrap();
    let grouped =
        writer::write_pack(&dataset, "core", &temp.path().join("grouped"), &options).unwrap();
    // Four blocks, one of them a covered empty block, fit one cells shard.
    assert_eq!(kinds(&grouped, "cells"), 1);
    assert_eq!(kinds(&grouped, "catalogue"), 1);
    let mut split_options = options.clone();
    split_options.shard_bytes = Some(1);
    let split =
        writer::write_pack(&dataset, "core", &temp.path().join("split"), &split_options).unwrap();
    assert_eq!(kinds(&split, "cells"), 4);
    assert!(kinds(&split, "catalogue") > 1);
    assert_ne!(split.input_digest, grouped.input_digest);
    let one = Pack::open(&temp.path().join("grouped"), true).unwrap();
    let many = Pack::open(&temp.path().join("split"), true).unwrap();
    for cell in [
        "8860140001fffff",
        "836014fffffffff",
        "8830800001fffff",
        "887eb50001fffff",
        "88f2930001fffff",
    ] {
        assert_eq!(
            one.from_h3(cell, true).unwrap(),
            many.from_h3(cell, true).unwrap()
        );
    }
    let empty = one.from_h3("887eb50001fffff", true).unwrap();
    assert_eq!(
        empty.evidence.unwrap().reason.as_deref(),
        Some("no_land"),
        "a covered empty block is land-free, not outside coverage"
    );
    for invalid in [0, writer::SHARD_TARGET_BYTES + 1] {
        let mut options = options.clone();
        options.shard_bytes = Some(invalid);
        let error =
            writer::write_pack(&dataset, "core", &temp.path().join("bad"), &options).unwrap_err();
        assert!(error.to_string().contains("shard_bytes"), "{error}");
    }
}

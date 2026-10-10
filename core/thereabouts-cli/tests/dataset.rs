//! `data install dataset` restores the dataset tree from table zips, all or nothing.
#![allow(
    clippy::unwrap_used,
    clippy::cast_possible_truncation,
    clippy::indexing_slicing
)]
mod support;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{fs, path::Path};
use support::Host;
use thereabouts_cli_core::zip::Crc32;

/// A stored zip in the layout the pipeline writes.
fn zip(entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut central = Vec::new();
    for (name, data) in entries {
        let offset = out.len() as u32;
        let mut crc = Crc32::default();
        crc.update(data);
        let fields = |out: &mut Vec<u8>| {
            for value in [crc.value(), data.len() as u32, data.len() as u32] {
                out.extend_from_slice(&value.to_le_bytes());
            }
            out.extend_from_slice(&(name.len() as u16).to_le_bytes());
            out.extend_from_slice(&0u16.to_le_bytes());
        };
        out.extend_from_slice(&0x0403_4b50u32.to_le_bytes());
        for value in [20u16, 0, 0, 0, 0x21] {
            out.extend_from_slice(&value.to_le_bytes());
        }
        fields(&mut out);
        out.extend_from_slice(name.as_bytes());
        out.extend_from_slice(data);
        central.extend_from_slice(&0x0201_4b50u32.to_le_bytes());
        for value in [0x0314u16, 20, 0, 0, 0, 0x21] {
            central.extend_from_slice(&value.to_le_bytes());
        }
        fields(&mut central);
        for value in [0u16, 0, 0] {
            central.extend_from_slice(&value.to_le_bytes());
        }
        central.extend_from_slice(&(0o100_644u32 << 16).to_le_bytes());
        central.extend_from_slice(&offset.to_le_bytes());
        central.extend_from_slice(name.as_bytes());
    }
    let start = out.len() as u32;
    out.extend_from_slice(&central);
    out.extend_from_slice(&0x0605_4b50u32.to_le_bytes());
    for value in [0u16, 0, entries.len() as u16, entries.len() as u16] {
        out.extend_from_slice(&value.to_le_bytes());
    }
    out.extend_from_slice(&(central.len() as u32).to_le_bytes());
    out.extend_from_slice(&start.to_le_bytes());
    out.extend_from_slice(&0u16.to_le_bytes());
    out
}
fn sha(data: &[u8]) -> String {
    format!("{:x}", Sha256::digest(data))
}
const CELLS: [(&str, &[u8]); 2] = [
    ("cells/group=8165bffffffffff/part.parquet", b"cells parquet"),
    ("cells/group=81653ffffffffff/part.parquet", b"more cells"),
];
const README: &[u8] = b"# Dataset\n";
/// A downloaded GitHub release: absolute URLs that a directory resolves by name.
fn release(root: &Path, member_digest: Option<&str>) {
    fs::create_dir_all(root).unwrap();
    let archive = zip(&CELLS);
    fs::write(root.join("dataset-cells.zip"), &archive).unwrap();
    fs::write(root.join("README.md"), README).unwrap();
    let base = "https://github.com/o/r/releases/download/v2026.10";
    let files: Vec<Value> = CELLS
        .iter()
        .map(|(path, data)| {
            json!({"path": path, "size": data.len(),
                "sha256": member_digest.map_or_else(|| sha(data), str::to_owned)})
        })
        .collect();
    let manifest = json!({
        "format": 1, "version": "2026.10",
        "archives": [{"name": "dataset-cells.zip", "table": "cells",
            "url": format!("{base}/dataset-cells.zip"), "asset_id": 3,
            "api_url": "https://api.github.com/repos/o/r/releases/assets/3",
            "size": archive.len(), "sha256": sha(&archive), "unpacked_size": 23,
            "files": files}],
        "files": [{"path": "README.md", "url": format!("{base}/README.md"),
            "size": README.len(), "sha256": sha(README)}],
    });
    let bytes = serde_json::to_vec(&manifest).unwrap();
    fs::write(root.join("dataset-manifest.json"), &bytes).unwrap();
    let index = json!({"format": 3, "datasets": {"2026.10": {"packs": {},
        "dataset": {"url": format!("{base}/dataset-manifest.json"),
            "size": bytes.len(), "sha256": sha(&bytes)}}}});
    fs::write(root.join("index.json"), serde_json::to_vec(&index).unwrap()).unwrap();
}
#[test]
fn the_dataset_tree_is_restored_and_reinstalling_verifies_it() {
    let temp = tempfile::tempdir().unwrap();
    let source = temp.path().join("release");
    release(&source, None);
    let store = temp.path().join("store");
    let mut host = Host::new(&store);
    let from = source.to_str().unwrap();
    assert_eq!(
        host.run(&["data", "install", "dataset", "--from", from]),
        0,
        "{}",
        host.err
    );
    let result: Value = serde_json::from_str(&host.out).unwrap();
    assert_eq!(result["dataset"]["installed"], true);
    assert_eq!(result["dataset"]["files"], 3);
    let tree = store.join("dataset/2026.10");
    for (path, data) in CELLS {
        assert_eq!(fs::read(tree.join(path)).unwrap(), data);
    }
    assert_eq!(fs::read(tree.join("README.md")).unwrap(), README);
    assert!(!store.join(".staging/dataset-2026.10").exists());
    assert_eq!(fs::read_dir(store.join(".downloads")).unwrap().count(), 0);
    assert_eq!(
        host.run(&[
            "data",
            "install",
            "dataset",
            "--version",
            "2026.10",
            "--from",
            from
        ]),
        0
    );
    let again: Value = serde_json::from_str(&host.out).unwrap();
    assert_eq!(again["dataset"]["installed"], false);
    fs::write(tree.join("README.md"), b"changed").unwrap();
    assert_eq!(host.run(&["data", "install", "dataset", "--from", from]), 4);
}
#[test]
fn a_member_that_differs_from_the_manifest_installs_nothing() {
    let temp = tempfile::tempdir().unwrap();
    let source = temp.path().join("release");
    release(&source, Some(&"0".repeat(64)));
    let store = temp.path().join("store");
    let mut host = Host::new(&store);
    let from = source.to_str().unwrap();
    assert_eq!(host.run(&["data", "install", "dataset", "--from", from]), 4);
    assert!(
        host.err.contains("differs from the dataset manifest"),
        "{}",
        host.err
    );
    assert!(!store.join("dataset").exists());
    assert!(!store.join(".staging/dataset-2026.10").exists());
}
#[test]
fn the_dataset_installs_alone_and_only_from_releases_that_ship_it() {
    let temp = tempfile::tempdir().unwrap();
    let source = temp.path().join("release");
    release(&source, None);
    let mut host = Host::new(&temp.path().join("store"));
    let from = source.to_str().unwrap();
    assert_eq!(
        host.run(&["data", "install", "dataset", "core", "--from", from]),
        2
    );
    assert!(host.err.contains("on its own"));
    assert_eq!(
        host.run(&[
            "data",
            "install",
            "dataset",
            "--version",
            "2026.09",
            "--from",
            from
        ]),
        4
    );
}

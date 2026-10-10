//! Environment errors and release changes offer actionable recovery without side effects.
#![allow(clippy::unwrap_used, clippy::indexing_slicing)]
mod support;
use std::fs;
use support::{Host, install, release};

#[test]
fn changing_version_cannot_hide_an_active_family() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("store");
    install(&root, &["core", "phone"]);
    let before = fs::read(root.join("active.json")).unwrap();
    let source = temp.path().join("release");
    release(&source);
    let path = source.join("index.json");
    let mut index: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    index["datasets"]["2027.01"] = index["datasets"]["2026.10"].clone();
    fs::write(&path, serde_json::to_vec(&index).unwrap()).unwrap();
    let mut host = Host::new(&root);
    assert_eq!(
        host.run(&[
            "data",
            "install",
            "phone",
            "--from",
            source.to_str().unwrap()
        ]),
        2
    );
    assert!(
        host.err
            .contains("thereabouts data install core phone --version 2027.01")
    );
    assert!(host.err.contains(" --from "));
    assert!(host.err.contains("--version 2026.10"));
    assert!(host.err.contains(source.to_str().unwrap()));
    assert_eq!(fs::read(root.join("active.json")).unwrap(), before);
    assert!(!root.join(".downloads").exists());
}

#[test]
fn missing_file_default_release_and_corrupt_pack_name_the_remedy() {
    let temp = tempfile::tempdir().unwrap();
    let mut host = Host::new(temp.path());
    // The default release is GitHub: with a token, an unsafe API override is refused
    // before any request, which proves the default without contacting github.com.
    host.env.insert("GITHUB_TOKEN".into(), "secret".into());
    host.env.insert(
        "THEREABOUTS_GITHUB_API_URL".into(),
        "http://api.example.com".into(),
    );
    assert_eq!(host.run(&["data", "install", "core"]), 2);
    assert!(
        host.err.contains("THEREABOUTS_GITHUB_API_URL"),
        "{}",
        host.err
    );
    assert!(!host.err.contains("secret"));
    host.env.remove("GITHUB_TOKEN");
    host.env.remove("THEREABOUTS_GITHUB_API_URL");
    install(temp.path(), &["core"]);
    let missing = temp.path().join("absent.csv");
    assert_eq!(host.run(&["reverse", missing.to_str().unwrap()]), 2);
    assert!(host.err.contains(missing.to_str().unwrap()));
    let root = thereabouts_cli::store::installed(temp.path(), "core").unwrap();
    let manifest = thereabouts_core::format::manifest::read(&root).unwrap();
    let artifact = &manifest
        .files
        .iter()
        .find(|f| f.kind == "cells")
        .unwrap()
        .path;
    fs::write(root.join(artifact), b"broken").unwrap();
    assert_eq!(host.run(&["reverse", "--lat", "0", "--lon", "0"]), 4);
    assert!(host.err.contains(root.to_str().unwrap()));
    assert!(host.err.contains("thereabouts data verify --full"));
    assert!(
        host.err
            .contains("thereabouts data remove core --yes && thereabouts data install core")
    );
}

//! Host sources retain handles and share native result/verification semantics.
#![allow(clippy::unwrap_used, clippy::expect_used)]
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};
use thereabouts_core::{
    Result,
    format::{
        Pack,
        reader::{ReadAt, Reader, Source},
    },
};
#[derive(Debug)]
struct Bytes(Vec<u8>);
impl ReadAt for Bytes {
    fn size(&self) -> u64 {
        self.0.len() as u64
    }
    fn read_at(&self, offset: u64, output: &mut [u8]) -> Result<()> {
        let start = usize::try_from(offset).unwrap();
        let bytes = self
            .0
            .get(start..start + output.len())
            .ok_or_else(|| std::io::Error::other("Short host read"))?;
        output.copy_from_slice(bytes);
        Ok(())
    }
}
struct Memory {
    files: BTreeMap<PathBuf, Arc<dyn ReadAt>>,
    opens: Mutex<BTreeMap<PathBuf, usize>>,
}
impl Source for Memory {
    fn open(&self, path: &Path) -> Result<Arc<dyn ReadAt>> {
        *self
            .opens
            .lock()
            .unwrap()
            .entry(path.to_owned())
            .or_default() += 1;
        self.files
            .get(path)
            .cloned()
            .ok_or_else(|| std::io::Error::other("Missing virtual artifact").into())
    }
}
#[test]
fn virtual_pack_has_native_results_and_one_open_per_artifact() {
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/packs/core-synthetic");
    let native = Pack::open(&fixture, true).unwrap();
    let root = Path::new("/virtual/core");
    let files = std::iter::once("manifest.json")
        .chain(native.manifest.files.iter().map(|f| f.path.as_str()))
        .map(|name| {
            (
                root.join(name),
                Arc::new(Bytes(std::fs::read(fixture.join(name)).unwrap())) as Arc<dyn ReadAt>,
            )
        })
        .collect();
    let source = Memory {
        files,
        opens: Mutex::default(),
    };
    let host = Pack::open_with(&Reader::new(root, &source), true).unwrap();
    assert!(source.opens.lock().unwrap().values().all(|n| *n == 1));
    drop(source); // Shards, rather than the admission cache, own the live handles.
    for cell in ["8860140001fffff", "836014fffffffff", "invalid"] {
        assert_eq!(
            host.from_h3(cell, true).unwrap(),
            native.from_h3(cell, true).unwrap()
        );
    }
}

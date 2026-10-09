//! Host sources share native result/verification semantics through a bounded handle pool.
#![allow(clippy::unwrap_used, clippy::expect_used)]
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
};
use thereabouts_core::{
    Result,
    format::{
        Pack,
        reader::{ReadAt, Reader, Source},
    },
};
/// Counts live handles so tests can bound concurrently open descriptors.
#[derive(Default, Debug)]
struct Live {
    now: AtomicUsize,
    peak: AtomicUsize,
}
#[derive(Debug)]
struct Bytes {
    bytes: Arc<Vec<u8>>,
    live: Arc<Live>,
}
impl Drop for Bytes {
    fn drop(&mut self) {
        self.live.now.fetch_sub(1, Ordering::SeqCst);
    }
}
impl ReadAt for Bytes {
    fn size(&self) -> u64 {
        self.bytes.len() as u64
    }
    fn read_at(&self, offset: u64, output: &mut [u8]) -> Result<()> {
        let start = usize::try_from(offset).unwrap();
        let bytes = self
            .bytes
            .get(start..start + output.len())
            .ok_or_else(|| std::io::Error::other("Short host read"))?;
        output.copy_from_slice(bytes);
        Ok(())
    }
}
struct Memory {
    files: BTreeMap<PathBuf, Arc<Vec<u8>>>,
    opens: Mutex<BTreeMap<PathBuf, usize>>,
    live: Arc<Live>,
}
impl Source for Memory {
    fn open(&self, path: &Path) -> Result<Arc<dyn ReadAt>> {
        *self
            .opens
            .lock()
            .unwrap()
            .entry(path.to_owned())
            .or_default() += 1;
        let bytes = self
            .files
            .get(path)
            .cloned()
            .ok_or_else(|| std::io::Error::other("Missing virtual artifact"))?;
        let now = self.live.now.fetch_add(1, Ordering::SeqCst) + 1;
        self.live.peak.fetch_max(now, Ordering::SeqCst);
        Ok(Arc::new(Bytes {
            bytes,
            live: Arc::clone(&self.live),
        }))
    }
}
fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join(format!("../../tests/fixtures/packs/{name}"))
}
fn memory(name: &str, root: &Path) -> (Pack, Arc<Memory>) {
    let fixture = fixture(name);
    let native = Pack::open(&fixture, true).unwrap();
    let files = std::iter::once("manifest.json")
        .chain(native.manifest.files.iter().map(|f| f.path.as_str()))
        .map(|name| {
            (
                root.join(name),
                Arc::new(std::fs::read(fixture.join(name)).unwrap()),
            )
        })
        .collect();
    let source = Arc::new(Memory {
        files,
        opens: Mutex::default(),
        live: Arc::default(),
    });
    (native, source)
}
#[test]
fn virtual_pack_has_native_results_and_one_open_per_artifact() {
    let root = Path::new("/virtual/core");
    let (native, source) = memory("core-synthetic", root);
    let host = Pack::open_with(&Reader::new(root, source.clone()), false).unwrap();
    // Within the default budget, admission and lookups never reopen an artifact.
    for cell in ["8860140001fffff", "836014fffffffff", "invalid"] {
        assert_eq!(
            host.from_h3(cell, true).unwrap(),
            native.from_h3(cell, true).unwrap()
        );
    }
    assert!(source.opens.lock().unwrap().values().all(|n| *n == 1));
}
#[test]
fn concurrent_lookups_beyond_the_pool_stay_correct_and_bounded() {
    let root = Path::new("/virtual/sample");
    let (native, source) = memory("core-sample", root);
    let reader = Reader::with_open_files(root, source.clone(), 2);
    let pack = Pack::open_with(&reader, true).unwrap();
    drop(reader);
    assert!(pack.manifest.files.len() > 4);
    let cells: Vec<String> = (0..800)
        .map(|i| {
            let lat = 49.0 + f64::from(i % 40) * 0.12;
            let lon = 2.0 + f64::from(i / 40) * 0.3;
            native.reverse(lat, lon, false).unwrap().cell.unwrap()
        })
        .collect();
    let threads = 8;
    std::thread::scope(|scope| {
        for chunk in cells.chunks(cells.len() / threads) {
            let (pack, native) = (&pack, &native);
            scope.spawn(move || {
                for cell in chunk {
                    assert_eq!(
                        pack.from_h3(cell, true).unwrap(),
                        native.from_h3(cell, true).unwrap()
                    );
                }
            });
        }
    });
    // Two idle handles plus at most one in-flight borrow per thread.
    let peak = source.live.peak.load(Ordering::SeqCst);
    assert!(peak <= 2 + threads, "peak live handles {peak}");
    assert!(source.opens.lock().unwrap().values().any(|n| *n > 1));
    drop(pack);
    assert_eq!(source.live.now.load(Ordering::SeqCst), 0);
}

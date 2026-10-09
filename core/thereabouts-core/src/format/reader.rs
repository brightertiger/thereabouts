//! Host-provided positioned reads through a bounded pool of reopenable handles.
use super::cache::Cache;
use crate::{Error, Result, error::ensure};
use sha2::{Digest, Sha256};
use std::{
    cell::RefCell,
    collections::BTreeMap,
    fmt::Debug,
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex, MutexGuard,
        atomic::{AtomicUsize, Ordering},
    },
};

/// Live host handles per pack. A world core has about a hundred artifacts; the
/// macOS default soft limit is 256 descriptors for the whole process.
pub const DEFAULT_OPEN_FILES: usize = 64;

/// An owned file snapshot/handle. Reads fill the requested span or return an error.
pub trait ReadAt: Debug + Send + Sync {
    /// Exact byte length captured when the handle was opened.
    fn size(&self) -> u64;
    /// Read exactly this range without moving a shared cursor.
    fn read_at(&self, offset: u64, bytes: &mut [u8]) -> Result<()>;
    /// Stable file identity, where the host has one; a reopened handle must match it.
    fn identity(&self) -> Option<(u64, u64)> {
        None
    }
}
/// Opening and path protection belong to the host; the pool may reopen a path.
pub trait Source: Send + Sync {
    /// Open a stable handle. Reject symlink artifacts and untrusted path traversal.
    fn open(&self, path: &Path) -> Result<Arc<dyn ReadAt>>;
}
/// Native host for Python and the Rust CLI. WASM callers must supply their own source.
pub struct Native;
#[cfg(not(target_arch = "wasm32"))]
#[derive(Debug)]
struct NativeFile {
    file: std::fs::File,
    size: u64,
    identity: Option<(u64, u64)>,
}
#[cfg(not(target_arch = "wasm32"))]
impl ReadAt for NativeFile {
    fn size(&self) -> u64 {
        self.size
    }
    fn read_at(&self, offset: u64, bytes: &mut [u8]) -> Result<()> {
        super::positioned::read(&self.file, bytes, offset)?;
        Ok(())
    }
    fn identity(&self) -> Option<(u64, u64)> {
        self.identity
    }
}
impl Source for Native {
    fn open(&self, path: &Path) -> Result<Arc<dyn ReadAt>> {
        #[cfg(not(target_arch = "wasm32"))]
        {
            let file = std::fs::File::open(path)?;
            let metadata = file.metadata()?;
            #[cfg(unix)]
            let identity = {
                use std::os::unix::fs::MetadataExt;
                Some((metadata.dev(), metadata.ino()))
            };
            #[cfg(not(unix))]
            let identity = None;
            Ok(Arc::new(NativeFile {
                file,
                size: metadata.len(),
                identity,
            }))
        }
        #[cfg(target_arch = "wasm32")]
        {
            let _ = path;
            Err(Error::Input("WASM requires a host file source".into()))
        }
    }
}
/// Least-recently-used live handles shared by every shard of one pack.
struct Pool {
    source: Arc<dyn Source>,
    handles: Mutex<Cache<usize, Arc<dyn ReadAt>>>,
    next: AtomicUsize,
}
impl Pool {
    fn handles(&self) -> Result<MutexGuard<'_, Cache<usize, Arc<dyn ReadAt>>>> {
        self.handles
            .lock()
            .map_err(crate::error::poisoned("handle pool"))
    }
    /// A full descriptor table first gives back this pack's idle handles.
    fn open(&self, path: &Path) -> Result<Arc<dyn ReadAt>> {
        match self.source.open(path) {
            Err(Error::ResourceLimit(_)) => {
                self.handles()?.clear();
                self.source.open(path)
            }
            result => result,
        }
    }
    fn get(&self, file: &Pooled) -> Result<Arc<dyn ReadAt>> {
        if let Some(handle) = self.handles()?.get(file.id) {
            return Ok(Arc::clone(&handle));
        }
        let handle = self.open(&file.path)?;
        // Positioned reads assume the admitted bytes; a replaced path is another pack.
        ensure(
            handle.size() == file.size && handle.identity() == file.identity,
            "Pack file changed while open; reopen the pack",
        )?;
        Ok(Arc::clone(&self.handles()?.insert(file.id, handle, 1)))
    }
}
/// A shard's view of one artifact: admitted size and identity, borrowing a live handle per read.
struct Pooled {
    pool: Arc<Pool>,
    id: usize,
    path: PathBuf,
    size: u64,
    identity: Option<(u64, u64)>,
}
impl Debug for Pooled {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Pooled")
            .field("path", &self.path)
            .field("size", &self.size)
            .finish_non_exhaustive()
    }
}
impl ReadAt for Pooled {
    fn size(&self) -> u64 {
        self.size
    }
    fn read_at(&self, offset: u64, bytes: &mut [u8]) -> Result<()> {
        self.pool.get(self)?.read_at(offset, bytes)
    }
    fn identity(&self) -> Option<(u64, u64)> {
        self.identity
    }
}
/// Admission context: one pooled view per path, shared by inventory, verification and shards.
/// At most the pool's capacity of host handles is open, plus one per in-flight read.
pub struct Reader {
    root: PathBuf,
    pool: Arc<Pool>,
    files: RefCell<BTreeMap<PathBuf, Arc<Pooled>>>,
}
impl Reader {
    /// Use a host source with the default handle budget.
    #[must_use]
    pub fn new(root: &Path, source: Arc<dyn Source>) -> Self {
        Self::with_open_files(root, source, DEFAULT_OPEN_FILES)
    }
    /// Use a host source holding at most `open_files` idle handles (minimum one).
    #[must_use]
    pub fn with_open_files(root: &Path, source: Arc<dyn Source>, open_files: usize) -> Self {
        Self {
            root: root.to_owned(),
            pool: Arc::new(Pool {
                source,
                handles: Mutex::new(Cache::new(open_files.max(1))),
                next: AtomicUsize::new(0),
            }),
            files: RefCell::new(BTreeMap::new()),
        }
    }
    /// Use native file handles with the default budget.
    #[must_use]
    pub fn native(root: &Path) -> Self {
        Self::new(root, Arc::new(Native))
    }
    pub(crate) fn open(&self, path: &Path) -> Result<Arc<dyn ReadAt>> {
        if let Some(file) = self.files.borrow().get(path) {
            return Ok(Arc::clone(file) as Arc<dyn ReadAt>);
        }
        let handle = self.pool.open(path)?;
        let file = Arc::new(Pooled {
            pool: Arc::clone(&self.pool),
            id: self.pool.next.fetch_add(1, Ordering::Relaxed),
            path: path.to_owned(),
            size: handle.size(),
            identity: handle.identity(),
        });
        self.pool.handles()?.insert(file.id, handle, 1);
        self.files
            .borrow_mut()
            .insert(path.to_owned(), Arc::clone(&file));
        Ok(file)
    }
    /// Close an artifact's handle now; a later read reopens and rechecks it.
    pub(crate) fn release(&self, path: &Path) -> Result<()> {
        if let Some(file) = self.files.borrow().get(path) {
            self.pool.handles()?.remove(file.id);
        }
        Ok(())
    }
    pub(crate) fn read(&self, path: &Path) -> Result<Vec<u8>> {
        let file = self.open(path)?;
        let size = super::container::index(file.size())?;
        ensure(size <= super::container::MAX_SHARD_BYTES, "Oversized file")?;
        let mut bytes = vec![0; size];
        file.read_at(0, &mut bytes)?;
        Ok(bytes)
    }
    pub(crate) fn digest(&self, path: &Path) -> Result<String> {
        let file = self.open(path)?;
        let mut hash = Sha256::new();
        let mut offset = 0;
        let mut buffer = vec![0; 65536];
        while offset < file.size() {
            let length = usize::try_from((file.size() - offset).min(65536))
                .map_err(|_| Error::Corrupt("Hash range overflow".into()))?;
            let bytes = buffer
                .get_mut(..length)
                .ok_or_else(|| Error::Corrupt("Hash range overflow".into()))?;
            file.read_at(offset, bytes)?;
            hash.update(bytes);
            offset += length as u64;
        }
        Ok(format!("{:x}", hash.finalize()))
    }
}
impl std::ops::Deref for Reader {
    type Target = Path;
    fn deref(&self) -> &Path {
        &self.root
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[cfg(unix)]
    fn evicted_handles_reopen_only_the_admitted_file() {
        let dir = tempfile::tempdir().unwrap();
        for name in ["a", "b"] {
            std::fs::write(dir.path().join(name), name.repeat(8)).unwrap();
        }
        let reader = Reader::with_open_files(dir.path(), Arc::new(Native), 1);
        let a = reader.open(&dir.path().join("a")).unwrap();
        let b = reader.open(&dir.path().join("b")).unwrap();
        let mut bytes = [0; 8];
        a.read_at(0, &mut bytes).unwrap(); // evicts b
        b.read_at(0, &mut bytes).unwrap(); // reopens b, evicts a
        assert_eq!(&bytes, b"bbbbbbbb");
        let replacement = dir.path().join("c");
        std::fs::write(&replacement, "c".repeat(8)).unwrap();
        std::fs::rename(&replacement, dir.path().join("a")).unwrap();
        let error = a.read_at(0, &mut bytes).unwrap_err();
        assert!(error.to_string().contains("changed while open"), "{error}");
        reader.release(&dir.path().join("b")).unwrap();
        b.read_at(0, &mut bytes).unwrap();
    }
}

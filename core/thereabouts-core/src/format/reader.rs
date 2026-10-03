//! Host-provided positioned reads. No lookup reopens a shard by pathname.
use crate::{Error, Result, error::ensure};
use sha2::{Digest, Sha256};
use std::{
    cell::RefCell,
    collections::BTreeMap,
    fmt::Debug,
    path::{Path, PathBuf},
    sync::Arc,
};

/// An owned file snapshot/handle. Reads fill the requested span or return an error.
pub trait ReadAt: Debug + Send + Sync {
    /// Exact byte length captured when the handle was opened.
    fn size(&self) -> u64;
    /// Read exactly this range without moving a shared cursor.
    fn read_at(&self, offset: u64, bytes: &mut [u8]) -> Result<()>;
}
/// Opening and path protection belong to the host; handles live until their last reader drops.
pub trait Source {
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
}
impl Source for Native {
    fn open(&self, path: &Path) -> Result<Arc<dyn ReadAt>> {
        #[cfg(not(target_arch = "wasm32"))]
        {
            let file = std::fs::File::open(path)?;
            let size = file.metadata()?.len();
            Ok(Arc::new(NativeFile { file, size }))
        }
        #[cfg(target_arch = "wasm32")]
        {
            let _ = path;
            Err(Error::Input("WASM requires a host file source".into()))
        }
    }
}
/// Admission context retains one handle per path across inventory, verification and opening.
/// Shards retain those same handles after admission; this cache does not retain file bytes.
pub struct Reader<'a> {
    root: PathBuf,
    source: &'a dyn Source,
    files: RefCell<BTreeMap<PathBuf, Arc<dyn ReadAt>>>,
}
impl<'a> Reader<'a> {
    /// Use a host source without filesystem or network calls in the reader policy.
    #[must_use]
    pub fn new(root: &Path, source: &'a dyn Source) -> Self {
        Self {
            root: root.to_owned(),
            source,
            files: RefCell::new(BTreeMap::new()),
        }
    }
    /// Use retained native file handles.
    #[must_use]
    pub fn native(root: &Path) -> Reader<'static> {
        Reader::new(root, &Native)
    }
    pub(crate) fn open(&self, path: &Path) -> Result<Arc<dyn ReadAt>> {
        if let Some(file) = self.files.borrow().get(path) {
            return Ok(Arc::clone(file));
        }
        let file = self.source.open(path)?;
        self.files
            .borrow_mut()
            .insert(path.to_owned(), Arc::clone(&file));
        Ok(file)
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
impl std::ops::Deref for Reader<'_> {
    type Target = Path;
    fn deref(&self) -> &Path {
        &self.root
    }
}

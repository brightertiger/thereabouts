//! Byte-range transfer boundary; installers can be tested without external networking.
use crate::error::{Error, Result};
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom},
    path::{Path, PathBuf},
};
use thereabouts_core::format::manifest;

/// Transfer sources return bytes beginning at exactly the requested offset.
pub trait Source {
    /// Explicit source spelling retained in copyable version-switch commands.
    fn origin(&self) -> Option<String> {
        None
    }

    /// Read a bounded release index.
    fn index(&self) -> Result<Vec<u8>>;
    /// Resume one immutable archive; implementations must validate Content-Range.
    fn open(&self, name: &str, offset: u64, total: u64) -> Result<Box<dyn Read>>;
}
/// An explicit local release directory containing index.json and tar archives.
pub struct Directory {
    root: PathBuf,
}
impl Directory {
    /// No directories are created while selecting a source.
    #[must_use]
    pub fn new(root: &Path) -> Self {
        Self {
            root: root.to_owned(),
        }
    }
}
impl Source for Directory {
    fn origin(&self) -> Option<String> {
        Some(self.root.to_string_lossy().into_owned())
    }
    fn index(&self) -> Result<Vec<u8>> {
        let path = manifest::artifact_path(&self.root, "index.json")?;
        if path.metadata()?.len() > 16 * 1024 * 1024 {
            return Err(Error::Integrity("Release index exceeds 16 MiB".into()));
        }
        Ok(std::fs::read(path)?)
    }
    fn open(&self, name: &str, offset: u64, total: u64) -> Result<Box<dyn Read>> {
        let mut file = File::open(manifest::artifact_path(&self.root, name)?)?;
        if file.metadata()?.len() != total || offset > total {
            return Err(Error::Integrity("Release archive size mismatch".into()));
        }
        file.seek(SeekFrom::Start(offset))?;
        Ok(Box::new(file))
    }
}

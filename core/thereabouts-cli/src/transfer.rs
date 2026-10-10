//! Byte-range transfer boundary; installers can be tested without external networking.
use crate::error::{Error, Result};
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom},
    path::{Path, PathBuf},
};
use thereabouts_core::format::manifest;

/// One release file: its index URL and, on GitHub, its asset API URL.
#[derive(Clone, Copy, Debug)]
pub struct Locator<'a> {
    /// Absolute URL or source-relative path, as the index lists it.
    pub url: &'a str,
    /// GitHub API URL of the asset, read instead of `url` when a token is set.
    pub api_url: Option<&'a str>,
}
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
    /// Resume one release file; a source holding a token may prefer its API URL.
    fn open_file(&self, file: Locator<'_>, offset: u64, total: u64) -> Result<Box<dyn Read>> {
        self.open(file.url, offset, total)
    }
}
/// A downloaded GitHub release keeps its flat asset names: an absolute URL in its index
/// names a file in the directory by its last path segment.
fn local_name(name: &str) -> &str {
    if name.starts_with("https://") || name.starts_with("http://") {
        name.rsplit('/').next().unwrap_or(name)
    } else {
        name
    }
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
        let mut file = File::open(manifest::artifact_path(&self.root, local_name(name))?)?;
        if file.metadata()?.len() != total || offset > total {
            return Err(Error::Integrity("Release archive size mismatch".into()));
        }
        file.seek(SeekFrom::Start(offset))?;
        Ok(Box::new(file))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;
    #[test]
    fn a_downloaded_release_resolves_absolute_urls_by_asset_name() {
        let temp = tempfile::tempdir().unwrap();
        std::fs::write(temp.path().join("core.tar.zst"), b"0123").unwrap();
        let source = Directory::new(temp.path());
        let url = "https://github.com/o/r/releases/download/v2026.10/core.tar.zst";
        let mut bytes = Vec::new();
        source
            .open_file(Locator { url, api_url: None }, 1, 4)
            .unwrap()
            .read_to_end(&mut bytes)
            .unwrap();
        assert_eq!(bytes, b"123");
        assert!(source.open("https://github.com/o/r/..", 0, 4).is_err());
    }
}

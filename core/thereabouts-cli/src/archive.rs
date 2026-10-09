//! Native staging output for the shared release-archive reader.
use crate::error::{Error, Result};
use std::{
    fs::{self, File, OpenOptions},
    io::{BufReader, Read},
    path::Path,
};
use thereabouts_cli_core::archive::{self, Output, Summary};
use thereabouts_core::format::manifest;

/// Files are created exclusively below the staging root and synced before verification.
struct Staging<'a> {
    root: &'a Path,
}
impl Output for Staging<'_> {
    fn directory(&mut self, path: &str) -> Result<()> {
        fs::create_dir_all(manifest::artifact_path(self.root, path)?)?;
        Ok(())
    }
    fn file(&mut self, path: &str, content: &mut dyn Read, size: u64) -> Result<()> {
        let destination = manifest::artifact_path(self.root, path)?;
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(destination)?;
        if std::io::copy(content, &mut file)? != size {
            return Err(Error::Integrity("Truncated archive entry".into()));
        }
        file.sync_all()?;
        Ok(())
    }
}
/// Expand a checksum-verified archive into an empty staging directory.
pub fn extract(archive: &Path, staging: &Path, unpacked_size: u64) -> Result<Summary> {
    archive::extract(
        BufReader::new(File::open(archive)?),
        &mut Staging { root: staging },
        unpacked_size,
    )
}

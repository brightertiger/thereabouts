//! Strict uncompressed POSIX ustar extraction with bounded allocation and no links.
use crate::error::{Error, Result};
use std::{
    collections::BTreeSet,
    fs::{self, OpenOptions},
    io::{Read, Seek, SeekFrom},
    path::Path,
};
use thereabouts_core::format::manifest;

/// Archives hold compressed pack blocks already; another compression layer is unnecessary.
/// Expanded content is bounded to the advertised archive size and a 1 GiB ceiling.
pub fn extract(reader: &mut (impl Read + Seek), output: &Path, bytes: u64) -> Result<()> {
    let mut paths = BTreeSet::new();
    let mut consumed = 0u64;
    let mut ended = false;
    loop {
        let mut header = [0; 512];
        reader.read_exact(&mut header)?;
        consumed += 512;
        if consumed > bytes {
            return Err(Error::Integrity("Archive exceeds advertised length".into()));
        }
        if header.iter().all(|b| *b == 0) {
            if ended {
                break;
            }
            ended = true;
            continue;
        }
        if ended {
            return Err(Error::Integrity("Invalid archive terminator".into()));
        }
        let get = |start, end| {
            header
                .get(start..end)
                .ok_or_else(|| Error::Integrity("Invalid tar field".into()))
        };
        let checksum = octal(get(148, 156)?)?;
        let sum: u64 = header
            .iter()
            .enumerate()
            .map(|(i, b)| {
                if (148..156).contains(&i) {
                    32
                } else {
                    u64::from(*b)
                }
            })
            .sum();
        if checksum != sum || get(257, 263)? != b"ustar\0" {
            return Err(Error::Integrity("Requires POSIX ustar archive".into()));
        }
        let name = text(get(0, 100)?)?;
        let prefix = text(get(345, 500)?)?;
        let path = if prefix.is_empty() {
            name.to_owned()
        } else {
            format!("{prefix}/{name}")
        };
        let kind = header.get(156).copied();
        let size = octal(get(124, 136)?)?;
        let padding = (512 - size % 512) % 512;
        consumed = consumed
            .checked_add(size)
            .and_then(|v| v.checked_add(padding))
            .filter(|v| *v <= bytes)
            .ok_or_else(|| Error::Integrity("Archive entry exceeds length".into()))?;
        let path = path.trim_end_matches('/');
        let destination = manifest::artifact_path(output, path)?;
        if !paths.insert(path.to_owned()) {
            return Err(Error::Integrity("Duplicate archive path".into()));
        }
        match kind {
            Some(b'5') if size == 0 => fs::create_dir_all(destination)?,
            Some(0 | b'0') => {
                if let Some(parent) = destination.parent() {
                    fs::create_dir_all(parent)?;
                }
                let mut file = OpenOptions::new()
                    .create_new(true)
                    .write(true)
                    .open(destination)?;
                let copied = std::io::copy(&mut reader.take(size), &mut file)?;
                if copied != size {
                    return Err(Error::Integrity("Truncated archive entry".into()));
                }
                file.sync_all()?;
                reader.seek(SeekFrom::Current(
                    i64::try_from(padding)
                        .map_err(|_| Error::Integrity("Invalid padding".into()))?,
                ))?;
            }
            _ => {
                return Err(Error::Integrity(
                    "Archive links and special entries are forbidden".into(),
                ));
            }
        }
    }
    trailer(reader, bytes.saturating_sub(consumed))
}
fn trailer(reader: &mut impl Read, bytes: u64) -> Result<()> {
    // tar pads records with zero blocks; reject appended payload.
    let mut tail = reader.take(bytes);
    let mut buffer = [0; 8192];
    loop {
        let count = tail.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        if buffer
            .get(..count)
            .is_none_or(|v| v.iter().any(|b| *b != 0))
        {
            return Err(Error::Integrity("Nonzero archive trailer".into()));
        }
    }
    Ok(())
}

fn text(bytes: &[u8]) -> Result<&str> {
    let end = bytes.iter().position(|b| *b == 0).unwrap_or(bytes.len());
    std::str::from_utf8(
        bytes
            .get(..end)
            .ok_or_else(|| Error::Integrity("Invalid tar name".into()))?,
    )
    .map_err(|_| Error::Integrity("Archive names must be UTF-8".into()))
}
fn octal(bytes: &[u8]) -> Result<u64> {
    u64::from_str_radix(text(bytes)?.trim(), 8)
        .map_err(|_| Error::Integrity("Invalid tar numeric field".into()))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn malformed_archives_do_not_extract() {
        let temp = tempfile::tempdir().unwrap();
        for bytes in [vec![], vec![1; 2048], vec![0; 512]] {
            let size = bytes.len() as u64;
            assert!(extract(&mut std::io::Cursor::new(bytes), temp.path(), size).is_err());
        }
        assert!(extract(&mut std::io::Cursor::new(vec![0; 1024]), temp.path(), 1024).is_ok());
    }
}

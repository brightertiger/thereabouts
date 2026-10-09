//! Release archives: one zstd frame holding a POSIX ustar stream of a pack directory.
//! The pipeline creates them, and the CLI, Python and Node extract them, through this module.
use crate::{
    error::{Error, Result},
    transport::MAX_UNPACKED_BYTES,
};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    io::{self, BufRead, BufReader, Read},
};

const BLOCK: usize = 512;
/// The installer writes this receipt into a pack; an archive may not supply it.
pub const RECEIPT: &str = ".archive.json";

/// One extracted regular file and the digest of the bytes written.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Entry {
    /// Validated relative path, `/`-separated.
    pub path: String,
    /// Exact file length.
    pub size: u64,
    /// Lowercase SHA-256 of the file.
    pub sha256: String,
}
/// Every regular file, in archive order, and the decompressed tar length.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Summary {
    /// Regular files in archive order.
    pub entries: Vec<Entry>,
    /// Exact length of the decompressed ustar stream.
    pub unpacked_size: u64,
}
/// Destination for extracted entries; paths are validated and relative to its root.
pub trait Output {
    /// Create a directory and its parents.
    fn directory(&mut self, path: &str) -> Result<()>;
    /// Create a new file (never replacing one) from exactly `size` bytes of `content`.
    fn file(&mut self, path: &str, content: &mut dyn Read, size: u64) -> Result<()>;
}
/// Inspection writes nothing; it only hashes the entries.
struct Discard;
impl Output for Discard {
    fn directory(&mut self, _: &str) -> Result<()> {
        Ok(())
    }
    fn file(&mut self, _: &str, content: &mut dyn Read, _: u64) -> Result<()> {
        io::copy(content, &mut io::sink())?;
        Ok(())
    }
}

/// Expand a verified archive, refusing unsafe entries and any byte beyond `unpacked_size`.
pub fn extract(archive: impl Read, output: &mut dyn Output, unpacked_size: u64) -> Result<Summary> {
    if unpacked_size > MAX_UNPACKED_BYTES {
        return Err(Error::Integrity(
            "Archive exceeds the unpacked size cap".into(),
        ));
    }
    let summary = walk(archive, output, unpacked_size)?;
    if summary.unpacked_size != unpacked_size {
        return Err(Error::Integrity(
            "Archive length differs from its declared unpacked size".into(),
        ));
    }
    Ok(summary)
}
/// List and hash every entry without writing, bounded by the unpacked size cap.
pub fn inspect(archive: impl Read) -> Result<Summary> {
    walk(archive, &mut Discard, MAX_UNPACKED_BYTES)
}

/// Decompressed bytes with a hard ceiling; stream faults are integrity failures.
struct Bounded<R> {
    inner: R,
    read: u64,
    limit: u64,
}
impl<R: Read> Read for Bounded<R> {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        let count = self.inner.read(buffer).map_err(|error| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                format!("Corrupt archive stream: {error}"),
            )
        })?;
        self.read += count as u64;
        if self.read > self.limit {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "Archive expands beyond its declared unpacked size",
            ));
        }
        Ok(count)
    }
}
/// Hash exactly the bytes handed to the output.
struct Hashing<'a, R> {
    inner: io::Take<&'a mut R>,
    hash: Sha256,
    count: u64,
}
impl<R: Read> Read for Hashing<'_, R> {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        let count = self.inner.read(buffer)?;
        if let Some(bytes) = buffer.get(..count) {
            self.hash.update(bytes);
        }
        self.count += count as u64;
        Ok(count)
    }
}
fn integrity(error: Error) -> Error {
    match error {
        Error::Io(error) if error.kind() == io::ErrorKind::InvalidData => {
            Error::Integrity(error.to_string())
        }
        Error::Io(error) if error.kind() == io::ErrorKind::UnexpectedEof => {
            Error::Integrity("Truncated archive".into())
        }
        other => other,
    }
}
fn walk(archive: impl Read, output: &mut dyn Output, limit: u64) -> Result<Summary> {
    let mut input = BufReader::new(archive);
    let decoder = ruzstd::decoding::StreamingDecoder::new(&mut input)
        .map_err(|error| Error::Integrity(format!("Requires a zstd archive: {error}")))?;
    let mut stream = Bounded {
        inner: decoder,
        read: 0,
        limit,
    };
    let entries = entries(&mut stream, output).map_err(integrity)?;
    let unpacked_size = stream.read;
    // One frame only: appended data would be an unverified second payload.
    if !input.fill_buf()?.is_empty() {
        return Err(Error::Integrity("Trailing data after archive".into()));
    }
    Ok(Summary {
        entries,
        unpacked_size,
    })
}
fn entries(stream: &mut impl Read, output: &mut dyn Output) -> Result<Vec<Entry>> {
    let mut entries = Vec::new();
    let mut seen = BTreeSet::new();
    loop {
        let mut header = [0; BLOCK];
        stream.read_exact(&mut header)?;
        if header.iter().all(|b| *b == 0) {
            stream.read_exact(&mut header)?;
            if header.iter().any(|b| *b != 0) {
                return Err(Error::Integrity("Invalid archive terminator".into()));
            }
            break;
        }
        let (path, kind, size) = parse(&header)?;
        if !seen.insert(path.clone()) {
            return Err(Error::Integrity("Duplicate archive path".into()));
        }
        match kind {
            b'5' if size == 0 => output.directory(&path)?,
            0 | b'0' => {
                let mut content = Hashing {
                    inner: stream.by_ref().take(size),
                    hash: Sha256::new(),
                    count: 0,
                };
                output.file(&path, &mut content, size)?;
                let Hashing { hash, count, .. } = content;
                if count != size {
                    return Err(Error::Integrity("Truncated archive entry".into()));
                }
                let padding = (BLOCK as u64 - size % BLOCK as u64) % BLOCK as u64;
                io::copy(&mut stream.by_ref().take(padding), &mut io::sink())?;
                entries.push(Entry {
                    path,
                    size,
                    sha256: format!("{:x}", hash.finalize()),
                });
            }
            _ => {
                return Err(Error::Integrity(
                    "Archive links and special entries are forbidden".into(),
                ));
            }
        }
    }
    // Writers may pad to a record size with zero blocks; reject any other payload.
    let mut buffer = [0; 8192];
    loop {
        let count = stream.read(&mut buffer)?;
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
    Ok(entries)
}
fn parse(header: &[u8; BLOCK]) -> Result<(String, u8, u64)> {
    let field = |start: usize, end: usize| {
        header
            .get(start..end)
            .ok_or_else(|| Error::Integrity("Invalid tar field".into()))
    };
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
    if octal(field(148, 156)?)? != sum || field(257, 263)? != b"ustar\0" {
        return Err(Error::Integrity("Requires POSIX ustar archive".into()));
    }
    let name = text(field(0, 100)?)?;
    let prefix = text(field(345, 500)?)?;
    let path = if prefix.is_empty() {
        name.to_owned()
    } else {
        format!("{prefix}/{name}")
    };
    let path = path.trim_end_matches('/');
    if path.is_empty()
        || path.starts_with('/')
        || path.contains(['\\', ':', '\0'])
        || path.split('/').any(|part| matches!(part, "" | "." | ".."))
        || path == RECEIPT
    {
        return Err(Error::Integrity("Unsafe or reserved archive path".into()));
    }
    Ok((path.to_owned(), header[156], octal(field(124, 136)?)?))
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
/// The single ustar header this module writes: mode 0644, zero owner and time.
#[cfg(feature = "create")]
fn header(path: &str, size: u64) -> Result<[u8; BLOCK]> {
    let mut header = [0; BLOCK];
    let mut put = |start: usize, value: &[u8]| {
        header
            .get_mut(start..start + value.len())
            .ok_or_else(|| Error::Integrity("Archive path is too long".into()))
            .map(|field| field.copy_from_slice(value))
    };
    if path.len() > 100 || size >= 1 << 33 {
        return Err(Error::Integrity("Archive entry cannot be encoded".into()));
    }
    put(0, path.as_bytes())?;
    put(100, b"0000644\0")?;
    put(108, b"0000000\0")?;
    put(116, b"0000000\0")?;
    put(124, format!("{size:011o}\0").as_bytes())?;
    put(136, b"00000000000\0")?;
    put(148, b"        ")?;
    put(156, b"0")?;
    put(257, b"ustar\0")?;
    put(263, b"00")?;
    let sum: u64 = header.iter().map(|b| u64::from(*b)).sum();
    header
        .get_mut(148..156)
        .ok_or_else(|| Error::Integrity("Invalid tar field".into()))?
        .copy_from_slice(format!("{sum:06o}\0 ").as_bytes());
    Ok(header)
}

#[cfg(feature = "create")]
pub use create::{Created, LEVEL, create};
#[cfg(feature = "create")]
mod create {
    use super::{BLOCK, Error, Result, header};
    use sha2::{Digest, Sha256};
    use std::{
        fs::File,
        io::{self, BufWriter, Read, Write},
        path::Path,
    };
    use thereabouts_core::format::manifest;

    /// Fixed level, single-threaded: identical packs give identical archive bytes.
    pub const LEVEL: i32 = 9;
    /// Archive identity recorded in the release index.
    #[derive(Clone, Debug, PartialEq, Eq)]
    pub struct Created {
        /// Compressed archive length.
        pub size: u64,
        /// Lowercase SHA-256 of the compressed archive.
        pub sha256: String,
        /// Exact decompressed ustar length.
        pub unpacked_size: u64,
    }
    struct Counted<W> {
        inner: W,
        hash: Sha256,
        count: u64,
    }
    impl<W: Write> Write for Counted<W> {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            let count = self.inner.write(bytes)?;
            if let Some(written) = bytes.get(..count) {
                self.hash.update(written);
            }
            self.count += count as u64;
            Ok(count)
        }
        fn flush(&mut self) -> io::Result<()> {
            self.inner.flush()
        }
    }
    /// Archive a verified pack directory: sorted paths, then a two-block terminator.
    pub fn create(pack: &Path, output: &Path) -> Result<Created> {
        let info = manifest::read(pack)?;
        let mut members: Vec<(String, Option<(u64, String)>)> = info
            .files
            .iter()
            .map(|f| (f.path.clone(), Some((f.size, f.sha256.clone()))))
            .chain(std::iter::once(("manifest.json".to_owned(), None)))
            .collect();
        members.sort();
        let file = File::create(output)?;
        let mut sink = Counted {
            inner: BufWriter::new(file.try_clone()?),
            hash: Sha256::new(),
            count: 0,
        };
        let mut encoder = zstd::stream::write::Encoder::new(&mut sink, LEVEL)?;
        encoder.include_checksum(true)?;
        let mut unpacked = 0;
        let mut buffer = vec![0; 1 << 20];
        for (name, expected) in members {
            let mut source = File::open(manifest::artifact_path(pack, &name)?)?;
            let size = source.metadata()?.len();
            encoder.write_all(&header(&name, size)?)?;
            let mut hash = Sha256::new();
            let mut copied = 0;
            loop {
                let count = source.read(&mut buffer)?;
                let Some(bytes) = buffer.get(..count).filter(|b| !b.is_empty()) else {
                    break;
                };
                hash.update(bytes);
                encoder.write_all(bytes)?;
                copied += count as u64;
            }
            let digest = format!("{:x}", hash.finalize());
            if copied != size
                || expected.is_some_and(|(length, sha256)| length != size || sha256 != digest)
            {
                return Err(Error::Integrity(format!(
                    "Pack file differs from its manifest: {name}"
                )));
            }
            let padding = (BLOCK as u64 - size % BLOCK as u64) % BLOCK as u64;
            encoder.write_all(&vec![0; usize::try_from(padding).unwrap_or(0)])?;
            unpacked += BLOCK as u64 + size + padding;
        }
        encoder.write_all(&[0; 2 * BLOCK])?;
        unpacked += 2 * BLOCK as u64;
        encoder.finish()?;
        sink.flush()?;
        drop(sink.inner);
        file.sync_all()?;
        Ok(Created {
            size: sink.count,
            sha256: format!("{:x}", sink.hash.finalize()),
            unpacked_size: unpacked,
        })
    }
}

#[cfg(test)]
#[allow(clippy::indexing_slicing)]
mod tests;

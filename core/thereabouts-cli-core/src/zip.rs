//! Dataset table archives: stored (uncompressed) zip files, one or more per table.
//! The pipeline writes them and the CLI, Python and Node restore a dataset through this
//! reader. Only the exact layout the pipeline writes is accepted: contiguous stored
//! entries without extra fields, data descriptors, comments or zip64 records, followed by
//! a central directory that repeats every local header. Paths follow the pack rules.
use crate::{
    archive::{self, Discard, Entry, Output, Summary, checked_path},
    error::{Error, Result},
    transport::MAX_UNPACKED_BYTES,
};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    io::{self, BufReader, Read},
};

const LOCAL: u32 = 0x0403_4b50;
const CENTRAL: u32 = 0x0201_4b50;
const END: u32 = 0x0605_4b50;
/// Bit 11 marks a UTF-8 name; every other flag (encryption, descriptors) is refused.
const UTF8: u16 = 0x0800;
/// Version 2.0 covers stored entries without zip64.
const VERSION: u16 = 20;
/// Without zip64 records an archive holds at most this many entries.
pub const MAX_ENTRIES: usize = 0xFFFF;
/// Longest entry name accepted.
const MAX_NAME: u16 = 4096;
/// Unix file-type bits of the external attributes: none, or a regular file.
const TYPE_MASK: u32 = 0o170_000;
const REGULAR: u32 = 0o100_000;
/// Name of the dataset install manifest uploaded beside the table archives.
pub const MANIFEST: &str = "dataset-manifest.json";
/// Dataset install manifest format.
pub const MANIFEST_FORMAT: u32 = 1;

/// Expand a checksum-verified zip, refusing unsafe entries and any byte beyond `unpacked_size`.
pub fn extract(zip: impl Read, output: &mut dyn Output, unpacked_size: u64) -> Result<Summary> {
    if unpacked_size > MAX_UNPACKED_BYTES {
        return Err(Error::Integrity(
            "Archive exceeds the unpacked size cap".into(),
        ));
    }
    let summary = walk(zip, output, unpacked_size).map_err(archive::integrity)?;
    if summary.unpacked_size != unpacked_size {
        return Err(Error::Integrity(
            "Archive length differs from its declared unpacked size".into(),
        ));
    }
    Ok(summary)
}
/// List and hash every entry without writing, bounded by the unpacked size cap.
pub fn inspect(zip: impl Read) -> Result<Summary> {
    walk(zip, &mut Discard, MAX_UNPACKED_BYTES).map_err(archive::integrity)
}

/// The IEEE CRC-32 that zip records for every entry.
#[derive(Clone, Copy, Debug)]
pub struct Crc32(u32);
#[allow(clippy::indexing_slicing)]
const fn crc_table() -> [u32; 256] {
    let mut table = [0; 256];
    let mut index = 0;
    while index < 256 {
        #[allow(clippy::cast_possible_truncation)]
        let mut value = index as u32;
        let mut bit = 0;
        while bit < 8 {
            value = if value & 1 == 1 {
                0xEDB8_8320 ^ (value >> 1)
            } else {
                value >> 1
            };
            bit += 1;
        }
        table[index] = value;
        index += 1;
    }
    table
}
static CRC_TABLE: [u32; 256] = crc_table();
impl Default for Crc32 {
    fn default() -> Self {
        Self(!0)
    }
}
impl Crc32 {
    /// Add bytes to the checksum.
    #[allow(clippy::cast_possible_truncation)]
    pub fn update(&mut self, bytes: &[u8]) {
        for byte in bytes {
            let slot = usize::from(self.0 as u8 ^ byte);
            self.0 = CRC_TABLE.get(slot).copied().unwrap_or(0) ^ (self.0 >> 8);
        }
    }
    /// The finished checksum.
    #[must_use]
    pub const fn value(self) -> u32 {
        !self.0
    }
}

/// Counts bytes consumed so header offsets can be checked against the stream position.
struct Counting<R> {
    inner: R,
    offset: u64,
}
impl<R: Read> Read for Counting<R> {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        let count = self.inner.read(buffer)?;
        self.offset += count as u64;
        Ok(count)
    }
}
/// Hash exactly the bytes handed to the output, with both digests zip and packs use.
struct Hashing<'a, R> {
    inner: io::Take<&'a mut R>,
    crc: Crc32,
    sha256: Sha256,
    count: u64,
}
impl<R: Read> Read for Hashing<'_, R> {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        let count = self.inner.read(buffer)?;
        if let Some(bytes) = buffer.get(..count) {
            self.crc.update(bytes);
            self.sha256.update(bytes);
        }
        self.count += count as u64;
        Ok(count)
    }
}
/// One local header as read, repeated exactly by its central directory record.
struct Local {
    flags: u16,
    time: u32,
    crc: u32,
    size: u32,
    offset: u32,
    name: Vec<u8>,
}
fn bytes<const N: usize>(input: &mut impl Read) -> Result<[u8; N]> {
    let mut value = [0; N];
    input.read_exact(&mut value)?;
    Ok(value)
}
fn u16_at(bytes: &[u8], at: usize) -> u16 {
    bytes
        .get(at..at + 2)
        .and_then(|b| b.try_into().ok())
        .map_or(0, u16::from_le_bytes)
}
fn u32_at(bytes: &[u8], at: usize) -> u32 {
    bytes
        .get(at..at + 4)
        .and_then(|b| b.try_into().ok())
        .map_or(0, u32::from_le_bytes)
}
fn refuse(message: &str) -> Error {
    Error::Integrity(format!("Unsupported dataset archive: {message}"))
}
fn offset32(offset: u64) -> Result<u32> {
    u32::try_from(offset).map_err(|_| refuse("larger than 4 GiB"))
}
/// Entries read so far: their local headers and what the output received.
#[derive(Default)]
struct Walked {
    locals: Vec<Local>,
    entries: Vec<Entry>,
    seen: BTreeSet<String>,
    total: u64,
}
fn walk(zip: impl Read, output: &mut dyn Output, limit: u64) -> Result<Summary> {
    let mut input = Counting {
        inner: BufReader::new(zip),
        offset: 0,
    };
    let mut read = Walked::default();
    let (signature, central) = loop {
        let offset = offset32(input.offset)?;
        let signature = u32::from_le_bytes(bytes::<4>(&mut input)?);
        if signature != LOCAL {
            break (signature, offset);
        }
        if read.locals.len() == MAX_ENTRIES {
            return Err(refuse("more than 65,535 entries"));
        }
        entry(&mut input, output, offset, limit, &mut read)?;
    };
    if read.locals.is_empty() {
        return Err(refuse("no entries"));
    }
    directory(&mut input, signature, &read.locals)?;
    let size = offset32(input.offset - u64::from(central))?;
    let end = bytes::<22>(&mut input)?;
    let count = u16::try_from(read.locals.len()).map_err(|_| refuse("too many entries"))?;
    if u32_at(&end, 0) != END
        || u16_at(&end, 4) != 0
        || u16_at(&end, 6) != 0
        || u16_at(&end, 8) != count
        || u16_at(&end, 10) != count
        || u32_at(&end, 12) != size
        || u32_at(&end, 16) != central
        || u16_at(&end, 20) != 0
    {
        return Err(refuse("end record differs from the central directory"));
    }
    if input.read(&mut [0; 1])? != 0 {
        return Err(Error::Integrity("Trailing data after archive".into()));
    }
    Ok(Summary {
        entries: read.entries,
        unpacked_size: read.total,
    })
}
/// One stored entry after its signature: header checks, then exactly its bytes to `output`.
fn entry<R: Read>(
    input: &mut R,
    output: &mut dyn Output,
    offset: u32,
    limit: u64,
    read: &mut Walked,
) -> Result<()> {
    let header = bytes::<26>(input)?;
    let (needed, flags, method) = (u16_at(&header, 0), u16_at(&header, 2), u16_at(&header, 4));
    let (time, crc) = (u32_at(&header, 6), u32_at(&header, 10));
    let (stored, size) = (u32_at(&header, 14), u32_at(&header, 18));
    let (name_length, extra) = (u16_at(&header, 22), u16_at(&header, 24));
    if needed > VERSION || flags & !UTF8 != 0 || method != 0 || stored != size || extra != 0 {
        return Err(refuse(
            "entries must be stored without flags or extra fields",
        ));
    }
    if !(1..=MAX_NAME).contains(&name_length) {
        return Err(refuse("invalid entry name length"));
    }
    let mut name = vec![0; usize::from(name_length)];
    input.read_exact(&mut name)?;
    let path = std::str::from_utf8(&name)
        .map_err(|_| Error::Integrity("Archive names must be UTF-8".into()))?
        .to_owned();
    if path.ends_with('/') {
        return Err(refuse("directory entries are not allowed"));
    }
    checked_path(&path)?;
    if !read.seen.insert(path.clone()) {
        return Err(Error::Integrity("Duplicate archive path".into()));
    }
    let length = u64::from(size);
    read.total = read
        .total
        .checked_add(length)
        .filter(|total| *total <= limit)
        .ok_or_else(|| {
            Error::Integrity("Archive expands beyond its declared unpacked size".into())
        })?;
    let mut content = Hashing {
        inner: input.by_ref().take(length),
        crc: Crc32::default(),
        sha256: Sha256::new(),
        count: 0,
    };
    output.file(&path, &mut content, length)?;
    let Hashing {
        crc: actual,
        sha256,
        count,
        ..
    } = content;
    if count != length {
        return Err(Error::Integrity("Truncated archive entry".into()));
    }
    if actual.value() != crc {
        return Err(Error::Integrity("Archive entry CRC-32 mismatch".into()));
    }
    read.entries.push(Entry {
        path,
        size: length,
        sha256: format!("{:x}", sha256.finalize()),
    });
    read.locals.push(Local {
        flags,
        time,
        crc,
        size,
        offset,
        name,
    });
    Ok(())
}
/// The central directory repeats every local header, in order, with nothing added.
fn directory<R: Read>(input: &mut R, first: u32, locals: &[Local]) -> Result<()> {
    let mut signature = first;
    for (position, local) in locals.iter().enumerate() {
        if position > 0 {
            signature = u32::from_le_bytes(bytes::<4>(input)?);
        }
        if signature != CENTRAL {
            return Err(refuse("central directory does not follow the entries"));
        }
        let record = bytes::<42>(input)?;
        let made_by = u16_at(&record, 0);
        let file_type = (u32_at(&record, 34) >> 16) & TYPE_MASK;
        let mut name = vec![0; usize::from(u16_at(&record, 24))];
        input.read_exact(&mut name)?;
        if u16_at(&record, 2) > VERSION
            || u16_at(&record, 4) != local.flags
            || u16_at(&record, 6) != 0
            || u32_at(&record, 8) != local.time
            || u32_at(&record, 12) != local.crc
            || u32_at(&record, 16) != local.size
            || u32_at(&record, 20) != local.size
            || u16_at(&record, 26) != 0
            || u16_at(&record, 28) != 0
            || u16_at(&record, 30) != 0
            || u32_at(&record, 38) != local.offset
            || name != local.name
        {
            return Err(refuse("central directory differs from the entries"));
        }
        if made_by >> 8 == 3 && file_type != 0 && file_type != REGULAR {
            return Err(Error::Integrity(
                "Archive links and special entries are forbidden".into(),
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests;

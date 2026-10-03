//! Checked little-endian containers, with no native alignment or unsafe casts.
use crate::{Error, Result, error::ensure};

/// A shard is bounded before allocation, including its directory and padding.
pub const MAX_SHARD_BYTES: usize = 64 * 1024 * 1024;
const MAGIC: &[u8; 8] = b"THEREPK\0";
/// Little-endian integer codecs shared by every record definition.
pub fn uint(bytes: &[u8], offset: usize, width: usize) -> Result<u64> {
    let span = bytes
        .get(
            offset
                ..offset
                    .checked_add(width)
                    .ok_or_else(|| Error::Corrupt("Integer overflow".into()))?,
        )
        .ok_or_else(|| Error::Corrupt("Truncated integer".into()))?;
    ensure(width <= 8, "Invalid integer width")?;
    let mut value = [0; 8];
    value[..width].copy_from_slice(span);
    Ok(u64::from_le_bytes(value))
}
/// Append the least significant bytes of a checked wire value.
pub fn put(bytes: &mut Vec<u8>, value: u64, width: usize) {
    bytes.extend_from_slice(&value.to_le_bytes()[..width]);
}
/// Checked host index conversion.
pub fn index(value: u64) -> Result<usize> {
    usize::try_from(value).map_err(|_| Error::Corrupt("Oversized span".into()))
}
/// A validated owned shard. Slices cannot outlive their bytes.
#[derive(Debug)]
pub struct Container {
    pub bytes: Vec<u8>,
    spans: Vec<(usize, usize)>,
}
impl Container {
    /// Validate the complete section directory before exposing any record.
    pub fn decode(bytes: Vec<u8>, kind: u32, widths: &[usize]) -> Result<Self> {
        ensure(
            bytes.len() <= MAX_SHARD_BYTES && bytes.get(..8) == Some(MAGIC),
            "Invalid shard magic or size",
        )?;
        ensure(
            uint(&bytes, 8, 2)? == 2 && uint(&bytes, 10, 2)? == 0,
            "Invalid shard version",
        )?;
        ensure(
            uint(&bytes, 12, 4)? == 0 && uint(&bytes, 16, 4)? == u64::from(kind),
            "Invalid shard flags or kind",
        )?;
        ensure(
            index(uint(&bytes, 20, 4)?)? == widths.len()
                && index(uint(&bytes, 24, 8)?)? == bytes.len(),
            "Invalid shard length",
        )?;
        let mut end = 32 + widths.len() * 32;
        let mut spans = Vec::new();
        for (i, width) in widths.iter().enumerate() {
            let pos = 32 + i * 32;
            ensure(
                uint(&bytes, pos, 4)? == (i + 1) as u64 && uint(&bytes, pos + 4, 4)? == 0,
                "Invalid section type or flags",
            )?;
            let start = index(uint(&bytes, pos + 8, 8)?)?;
            let len = index(uint(&bytes, pos + 16, 8)?)?;
            let count = index(uint(&bytes, pos + 24, 8)?)?;
            let stop = start
                .checked_add(len)
                .ok_or_else(|| Error::Corrupt("Span overflow".into()))?;
            ensure(
                start == end.next_multiple_of(8)
                    && stop <= bytes.len()
                    && count.checked_mul(*width) == Some(len),
                "Invalid section span",
            )?;
            ensure(
                bytes
                    .get(end..start)
                    .is_some_and(|p| p.iter().all(|b| *b == 0)),
                "Nonzero alignment padding",
            )?;
            spans.push((start, stop));
            end = stop;
        }
        ensure(end == bytes.len(), "Trailing bytes")?;
        Ok(Self { bytes, spans })
    }
    /// Section number is zero-based inside the implementation.
    #[must_use]
    pub fn section(&self, number: usize) -> &[u8] {
        let (a, b) = self.spans[number];
        &self.bytes[a..b]
    }
}
/// Encode exactly the layout that `Container::decode` accepts.
pub fn encode(kind: u32, sections: &[(&[u8], usize)]) -> Result<Vec<u8>> {
    let mut bytes = vec![0; 32 + sections.len() * 32];
    bytes[..8].copy_from_slice(MAGIC);
    bytes[8..10].copy_from_slice(&2_u16.to_le_bytes());
    bytes[16..20].copy_from_slice(&kind.to_le_bytes());
    bytes[20..24].copy_from_slice(
        &u32::try_from(sections.len())
            .map_err(|_| Error::Input("Too many sections".into()))?
            .to_le_bytes(),
    );
    for (i, (data, width)) in sections.iter().enumerate() {
        ensure(data.len() % width == 0, "Partial record")?;
        bytes.resize(bytes.len().next_multiple_of(8), 0);
        let mut entry = Vec::new();
        put(&mut entry, (i + 1) as u64, 4);
        put(&mut entry, 0, 4);
        put(&mut entry, bytes.len() as u64, 8);
        put(&mut entry, data.len() as u64, 8);
        put(&mut entry, (data.len() / width) as u64, 8);
        bytes[32 + i * 32..64 + i * 32].copy_from_slice(&entry);
        bytes.extend_from_slice(data);
    }
    let len = bytes.len() as u64;
    bytes[24..32].copy_from_slice(&len.to_le_bytes());
    ensure(bytes.len() <= MAX_SHARD_BYTES, "Shard exceeds memory limit")?;
    Ok(bytes)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn padding_and_truncation() {
        let b = encode(4, &[(b"abc", 1), (b"d", 1)]).unwrap();
        assert_eq!(
            Container::decode(b.clone(), 4, &[1, 1]).unwrap().section(1),
            b"d"
        );
        for i in 0..b.len() {
            assert!(Container::decode(b[..i].to_vec(), 4, &[1, 1]).is_err());
        }
    }
}

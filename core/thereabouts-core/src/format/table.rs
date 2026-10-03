//! Compressed table directories and bounded decoded-block ownership.
use super::{
    cache::Cache,
    columns,
    container::{FileShard, index, put, uint},
    manifest::{self, Manifest},
};
use crate::{Error, Result, error::ensure};
use std::sync::{Arc, Mutex};
/// Each directory row contains row range, compressed span and first search key.
pub const DIRECTORY_WIDTH: usize = 48;
/// Integer and UTF-8 tables have distinct container kinds.
pub const INTEGER_KIND: u32 = 9;
/// String IDs address one pack-level pool, partitioned by evidence access.
pub const STRING_KIND: u32 = 10;
/// One decoded table block; strings and numeric columns have separate wire tags.
#[derive(Debug)]
pub(crate) enum Data {
    Integers(Vec<Vec<u64>>),
    Starts(Vec<[u64; 3]>),
    Strings(Vec<String>),
}
/// One shared budget per forward pack, allocated lazily. The 7.8M-interval
/// workload has 15.6M starts/gaps: 374.4 MB as 24-byte rows. 512 MiB retains
/// that working set and its small dictionaries without a budget per table.
pub(crate) const DECODED_BLOCK_CACHE_BYTES: usize = 512 * 1024 * 1024;
pub(crate) type BlockCache = Arc<Mutex<Cache<(usize, usize), Data>>>;
pub(crate) fn block_cache() -> BlockCache {
    Arc::new(Mutex::new(Cache::new(DECODED_BLOCK_CACHE_BYTES)))
}
#[derive(Debug)]
struct Block {
    file: Arc<FileShard>,
    first: usize,
    rows: usize,
    raw: usize,
    offset: usize,
    length: usize,
    key: u128,
}
/// Resident block directories; payloads enter the byte-budget LRU only on demand.
#[derive(Debug)]
pub(crate) struct Table {
    blocks: Vec<Block>,
    kind: u32,
    keyed: bool,
    pub(crate) rows: usize,
    cache: BlockCache,
    identity: usize,
}
impl Table {
    pub(crate) fn open(
        root: &super::reader::Reader<'_>,
        manifest: &Manifest,
        role: &str,
        kind: u32,
        cache: BlockCache,
        identity: usize,
    ) -> Result<Self> {
        let keyed = matches!(role, "starts4" | "starts6");
        let mut blocks = Vec::<Block>::new();
        let mut rows = 0;
        for artifact in manifest.files.iter().filter(|f| f.kind == role) {
            let file = Arc::new(FileShard::from_file(
                root.open(&manifest::artifact_path(root, &artifact.path)?)?,
                kind,
                &[DIRECTORY_WIDTH, 1],
            )?);
            let directory = file.section(0)?;
            let mut end = 0;
            for bytes in directory.as_chunks::<DIRECTORY_WIDTH>().0 {
                let first = index(uint(bytes, 0, 8)?)?;
                let count = index(uint(bytes, 8, 4)?)?;
                let raw = index(uint(bytes, 12, 4)?)?;
                let offset = index(uint(bytes, 16, 8)?)?;
                let length = index(uint(bytes, 24, 4)?)?;
                let key = u128::from(uint(bytes, 32, 8)?) | (u128::from(uint(bytes, 40, 8)?) << 64);
                ensure(
                    first == rows
                        && (1..=columns::BLOCK_ROWS).contains(&count)
                        && raw <= columns::BLOCK_BYTES
                        && length <= columns::BLOCK_BYTES
                        && offset == end
                        && uint(bytes, 28, 4)? == 0,
                    "Invalid compressed block directory",
                )?;
                end = offset
                    .checked_add(length)
                    .ok_or_else(|| Error::Corrupt("Block span overflow".into()))?;
                ensure(end <= file.len(1)?, "Truncated compressed block")?;
                rows = rows
                    .checked_add(count)
                    .ok_or_else(|| Error::Corrupt("Table row overflow".into()))?;
                ensure(
                    !keyed || blocks.last().is_none_or(|b| b.key < key),
                    "Unsorted block keys",
                )?;
                blocks.push(Block {
                    file: Arc::clone(&file),
                    first,
                    rows: count,
                    raw,
                    offset,
                    length,
                    key,
                });
            }
            ensure(end == file.len(1)?, "Trailing compressed payload")?;
        }
        Ok(Self {
            blocks,
            kind,
            keyed,
            rows,
            cache,
            identity,
        })
    }
    fn block(&self, number: usize) -> Result<Arc<Data>> {
        if let Some(data) = self
            .cache
            .lock()
            .map_err(|_| Error::Corrupt("Poisoned table cache".into()))?
            .get((self.identity, number))
        {
            return Ok(data);
        }
        let b = self
            .blocks
            .get(number)
            .ok_or_else(|| Error::Corrupt("Missing block".into()))?;
        let raw = columns::decompress(&b.file.range(1, b.offset, b.length)?, b.raw)?;
        let (data, size) = if self.kind == INTEGER_KIND {
            let rows = columns::decode(&raw)?;
            ensure(rows.len() == b.rows, "Column count/directory disagreement")?;
            if self.keyed {
                let mut previous = None;
                for row in &rows {
                    let key = integer_key(row)?;
                    ensure(previous.is_none_or(|p| p < key), "Unsorted starts in block")?;
                    previous = Some(key);
                }
                ensure(
                    rows.first().map(|r| integer_key(r)).transpose()? == Some(b.key),
                    "Start directory key disagrees",
                )?;
            }
            if self.keyed {
                let starts = rows
                    .into_iter()
                    .map(|r| {
                        r.try_into()
                            .map_err(|_| Error::Corrupt("Invalid start width".into()))
                    })
                    .collect::<Result<Vec<[u64; 3]>>>()?;
                let size = starts.capacity() * size_of::<[u64; 3]>();
                (Data::Starts(starts), size)
            } else {
                let size = rows.capacity() * size_of::<Vec<u64>>()
                    + rows.iter().map(|r| r.capacity() * 8).sum::<usize>();
                (Data::Integers(rows), size)
            }
        } else {
            let values = decode_strings(&raw, b.rows)?;
            let size = values.capacity() * size_of::<String>()
                + values.iter().map(String::capacity).sum::<usize>();
            (Data::Strings(values), size)
        };
        Ok(self
            .cache
            .lock()
            .map_err(|_| Error::Corrupt("Poisoned table cache".into()))?
            .insert((self.identity, number), data, size + size_of::<Data>()))
    }
    fn locate(&self, row: usize) -> Result<(Arc<Data>, usize)> {
        ensure(row < self.rows, "Dangling table row")?;
        let number = self
            .blocks
            .partition_point(|b| b.first <= row)
            .checked_sub(1)
            .ok_or_else(|| Error::Corrupt("Missing table block".into()))?;
        let first = self
            .blocks
            .get(number)
            .ok_or_else(|| Error::Corrupt("Missing table directory".into()))?
            .first;
        Ok((self.block(number)?, row - first))
    }
    pub(crate) fn row(&self, row: usize) -> Result<Vec<u64>> {
        let (data, row) = self.locate(row)?;
        match data.as_ref() {
            Data::Integers(rows) => rows.get(row).cloned(),
            Data::Starts(rows) => rows.get(row).map(|r| r.to_vec()),
            Data::Strings(_) => None,
        }
        .ok_or_else(|| Error::Corrupt("Missing numeric row".into()))
    }
    pub(crate) fn string(&self, row: usize) -> Result<String> {
        let (data, row) = self.locate(row)?;
        let Data::Strings(rows) = data.as_ref() else {
            return Err(Error::Corrupt("Expected string pool".into()));
        };
        rows.get(row)
            .cloned()
            .ok_or_else(|| Error::Corrupt("Missing pool string".into()))
    }
    pub(crate) fn block_at_key(&self, key: u128) -> Result<Option<(Arc<Data>, usize)>> {
        let Some(i) = self.blocks.partition_point(|b| b.key <= key).checked_sub(1) else {
            return Ok(None);
        };
        let b = self
            .blocks
            .get(i)
            .ok_or_else(|| Error::Corrupt("Missing key directory".into()))?;
        Ok(Some((self.block(i)?, b.first)))
    }
    pub(crate) fn verify(&self) -> Result<()> {
        for i in 0..self.blocks.len() {
            self.block(i)?;
        }
        Ok(())
    }
}
/// Choose offsets or front coding by compressed size while preserving pool row IDs.
pub fn encode_strings(values: &[String]) -> Result<Vec<u8>> {
    ensure(
        (1..=columns::BLOCK_ROWS).contains(&values.len()),
        "Invalid string row count",
    )?;
    let mut offsets = Vec::new();
    let mut text = Vec::new();
    put(&mut offsets, 0, 4);
    for value in values {
        text.extend_from_slice(value.as_bytes());
        put(&mut offsets, text.len() as u64, 4);
    }
    offsets.extend(text);
    ensure(
        offsets.len() <= columns::BLOCK_BYTES,
        "Oversized string pool block",
    )?;
    let mut best = offsets;
    let mut size = columns::compress(&best)?.len();
    for (reverse, separate) in [(false, false), (true, false), (false, true), (true, true)] {
        if let Ok(front) = super::string_block::encode(values, reverse, separate) {
            let length = columns::compress(&front)?.len();
            if length < size {
                best = front;
                size = length;
            }
        }
    }
    Ok(best)
}
/// Decode an admitted pool block and restore original row IDs after front coding.
pub fn decode_strings(bytes: &[u8], rows: usize) -> Result<Vec<String>> {
    ensure(
        (1..=columns::BLOCK_ROWS).contains(&rows) && bytes.len() <= columns::BLOCK_BYTES,
        "Invalid string block shape",
    )?;
    if uint(bytes, 0, 4)? >= u64::from(u32::MAX - 3) {
        return super::string_block::decode(bytes, rows);
    }
    let start = (rows + 1) * 4;
    ensure(
        start <= bytes.len() && uint(bytes, 0, 4)? == 0,
        "Invalid string pool offsets",
    )?;
    let mut values = Vec::new();
    let mut previous = 0;
    for row in 0..rows {
        let end = index(uint(bytes, (row + 1) * 4, 4)?)?;
        let span = bytes
            .get(start + previous..start + end)
            .ok_or_else(|| Error::Corrupt("Invalid pool string span".into()))?;
        values.push(
            std::str::from_utf8(span)
                .map_err(|_| Error::Corrupt("Invalid pool UTF-8".into()))?
                .to_owned(),
        );
        previous = end;
    }
    ensure(start + previous == bytes.len(), "Trailing pool bytes")?;
    Ok(values)
}

/// Address starts have two u64 words followed by a location reference.
fn integer_key(row: &[u64]) -> Result<u128> {
    ensure(row.len() == 3, "Invalid start row")?;
    let high = row
        .first()
        .ok_or_else(|| Error::Corrupt("Missing start".into()))?;
    let low = row
        .get(1)
        .ok_or_else(|| Error::Corrupt("Missing start".into()))?;
    Ok((u128::from(*high) << 64) | u128::from(*low))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn decoded_blocks_are_shared_without_colliding_between_tables() {
        let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/packs/ip-sample");
        let manifest = manifest::read(&root).unwrap();
        let cache = block_cache();
        let starts = Table::open(
            &super::super::reader::Reader::native(&root),
            &manifest,
            "starts4",
            INTEGER_KIND,
            Arc::clone(&cache),
            0,
        )
        .unwrap();
        let strings = Table::open(
            &super::super::reader::Reader::native(&root),
            &manifest,
            "strings",
            STRING_KIND,
            cache,
            1,
        )
        .unwrap();
        let file = &starts.blocks[0].file;
        file.reads.lock().unwrap().clear();
        let first = starts.block(0).unwrap();
        assert!(matches!(first.as_ref(), Data::Starts(_)));
        assert_eq!(file.reads.lock().unwrap().len(), 1);
        assert!(Arc::ptr_eq(&first, &starts.block(0).unwrap()));
        assert_eq!(file.reads.lock().unwrap().len(), 1);
        assert!(matches!(
            strings.block(0).unwrap().as_ref(),
            Data::Strings(_)
        ));
        assert!(Arc::ptr_eq(&first, &starts.block(0).unwrap()));
        assert_eq!(file.reads.lock().unwrap().len(), 1);
    }
}

//! Sparse resolution-three blocks with dictionary-coded, timezone-aware labels.
use super::{
    address,
    container::{Container, encode, index, put, uint},
};
use crate::{Result, error::ensure};
use h3o::CellIndex;
use std::collections::{BTreeMap, BTreeSet};

/// Country, subdivision, final city, method flags, and timezone-set reference.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Default)]
pub struct Label(pub [u32; 5]);
impl Label {
    /// Shared twenty-byte wire layout; zero references are null.
    #[allow(clippy::many_single_char_names)] // Directory offsets mirror the wire layout.
    #[allow(clippy::indexing_slicing)] // directory validates all section ranges before these slices.
    pub fn decode(bytes: &[u8], start: usize) -> Result<Self> {
        let mut fields = [0; 5];
        for (i, field) in fields.iter_mut().enumerate() {
            *field = u32::try_from(uint(bytes, start + 4 * i, 4)?)
                .map_err(|_| crate::Error::Corrupt("Invalid u32".into()))?;
        }
        Ok(Self(fields))
    }
    /// Append all five fields in their normative order.
    pub fn encode(self, bytes: &mut Vec<u8>) {
        for field in self.0 {
            put(bytes, u64::from(field), 4);
        }
    }
    /// Validate references, reserved bits, and method/null agreement.
    pub fn validate(self, places: usize, zones: usize) -> Result<()> {
        let [country, state, city, flags, timezone] = self.0;
        ensure(
            [country, state, city].iter().all(|r| *r as usize <= places)
                && (timezone as usize) < zones,
            "Dangling spatial reference",
        )?;
        ensure(
            flags & !63 == 0
                && (city != 0) == (flags & 7 != 0)
                && (country != 0) == (flags & 8 != 0)
                && (state != 0) == (flags & 16 != 0),
            "Invalid label methods",
        )
    }
}
/// A validated per-block index into an owned shard.
#[derive(Debug)]
pub struct Block {
    /// Sorted sparse logical keys, disjoint from their stored ancestors.
    pub keys: Vec<u16>,
    /// One validated label per key, in identical order.
    pub labels: Vec<Label>,
}
impl Block {
    /// First stored logical ancestor, without reindexing the coordinate.
    #[must_use]
    pub fn lookup(&self, cell: CellIndex) -> Option<(u16, Label)> {
        address::ancestors(cell).iter().find_map(|key| {
            self.keys
                .binary_search(key)
                .ok()
                .and_then(|i| self.labels.get(i).map(|label| (*key, *label)))
        })
    }
}
/// Offsets into the three spatial data sections, validated without reading payloads.
#[derive(Clone, Debug)]
pub(crate) struct Entry {
    pub(crate) block: u32,
    count: usize,
    width: usize,
    dictionary_count: usize,
    pub(crate) spans: [(usize, usize); 3],
}
#[allow(clippy::indexing_slicing)] // Parallel three-element arrays are iterated only over 0..3.
pub(crate) fn directory(bytes: &[u8], lengths: [usize; 3]) -> Result<Vec<Entry>> {
    let mut entries = Vec::new();
    let mut ends = [0; 3];
    for row in bytes.as_chunks::<40>().0 {
        let block = u32::try_from(uint(row, 0, 4)?)
            .map_err(|_| crate::Error::Corrupt("Invalid u32".into()))?;
        address::cell_at(block, 0)?;
        ensure(
            entries.last().is_none_or(|last: &Entry| last.block < block),
            "Unsorted blocks",
        )?;
        let count = index(uint(row, 4, 4)?)?;
        let width = index(uint(row, 16, 4)?)?;
        let dictionary_count = index(uint(row, 20, 4)?)?;
        let starts = [
            index(uint(row, 8, 8)?)?,
            index(uint(row, 24, 8)?)?,
            index(uint(row, 32, 8)?)?,
        ];
        ensure(
            count <= 16807 && width <= 2 && starts == ends,
            "Invalid block spans",
        )?;
        ensure(
            if width == 0 {
                dictionary_count == 0
            } else {
                dictionary_count > 0
                    && dictionary_count <= count
                    && dictionary_count <= (1 << (8 * width))
            },
            "Invalid dictionary size",
        )?;
        let sizes = [
            count * 2,
            count * if width == 0 { 20 } else { width },
            dictionary_count * 20,
        ];
        let spans = std::array::from_fn(|i| (starts[i], sizes[i]));
        for i in 0..3 {
            ends[i] = starts[i]
                .checked_add(sizes[i])
                .ok_or_else(|| crate::Error::Corrupt("Block span overflow".into()))?;
            ensure(ends[i] <= lengths[i], "Block exceeds sections")?;
        }
        entries.push(Entry {
            block,
            count,
            width,
            dictionary_count,
            spans,
        });
    }
    ensure(ends == lengths, "Unconsumed spatial bytes")?;
    Ok(entries)
}
pub(crate) fn decode_block(
    entry: &Entry,
    keys: &[u8],
    values: &[u8],
    labels: &[u8],
    places: usize,
    zones: usize,
) -> Result<Block> {
    let mut dictionary = Vec::new();
    for i in 0..entry.dictionary_count {
        let label = Label::decode(labels, i * 20)?;
        label.validate(places, zones)?;
        ensure(
            dictionary.last().is_none_or(|last| *last < label),
            "Unsorted label dictionary",
        )?;
        dictionary.push(label);
    }
    let mut decoded_keys = Vec::with_capacity(entry.count);
    let mut decoded_labels = Vec::with_capacity(entry.count);
    for i in 0..entry.count {
        let key = u16::try_from(uint(keys, i * 2, 2)?)
            .map_err(|_| crate::Error::Corrupt("Invalid u16".into()))?;
        let cell = address::cell_at(entry.block, key)?;
        ensure(
            decoded_keys.last().is_none_or(|last| *last < key),
            "Unsorted keys",
        )?;
        ensure(
            address::ancestors(cell)
                .iter()
                .skip(1)
                .all(|a| decoded_keys.binary_search(a).is_err()),
            "Overlapping stored ancestors",
        )?;
        let label = if entry.width == 0 {
            Label::decode(values, i * 20)?
        } else {
            let selector = index(uint(values, i * entry.width, entry.width)?)?;
            *dictionary
                .get(selector)
                .ok_or_else(|| crate::Error::Corrupt("Dangling dictionary selector".into()))?
        };
        label.validate(places, zones)?;
        decoded_keys.push(key);
        decoded_labels.push(label);
    }
    Ok(Block {
        keys: decoded_keys,
        labels: decoded_labels,
    })
}
/// Decode and validate the entire spatial shard, including ancestor disjointness.
#[allow(clippy::indexing_slicing)] // directory validates all section ranges before these slices.
pub fn decode(bytes: Vec<u8>, places: usize, zones: usize) -> Result<BTreeMap<u32, Block>> {
    let container = Container::decode(bytes, 1, &[40, 2, 1, 20])?;
    let entries = directory(
        container.section(0),
        std::array::from_fn(|i| container.section(i + 1).len()),
    )?;
    let mut blocks = BTreeMap::new();
    for entry in entries {
        let spans: [&[u8]; 3] = std::array::from_fn(|i| {
            let (start, len) = entry.spans[i];
            &container.section(i + 1)[start..start + len]
        });
        blocks.insert(
            entry.block,
            decode_block(&entry, spans[0], spans[1], spans[2], places, zones)?,
        );
    }
    Ok(blocks)
}
/// Selector width: zero stores labels flat; otherwise one or two bytes index a dictionary.
fn width(rows: usize, labels: usize) -> usize {
    let width = if labels <= 256 { 1 } else { 2 };
    if labels * 20 + rows * width >= rows * 20 {
        0
    } else {
        width
    }
}
/// Bytes one block adds to a shard, excluding the container header and section padding.
#[must_use]
pub fn block_bytes(rows: &[(u16, Label)]) -> usize {
    let labels = rows.iter().map(|(_, l)| *l).collect::<BTreeSet<_>>().len();
    40 + rows.len() * 2
        + match width(rows.len(), labels) {
            0 => rows.len() * 20,
            width => rows.len() * width + labels * 20,
        }
}
/// Incremental shard encoder: memory follows encoded bytes, not decoded rows.
#[derive(Debug, Default)]
pub struct Blocks {
    directory: Vec<u8>,
    keys: Vec<u8>,
    values: Vec<u8>,
    dictionary: Vec<u8>,
    last: Option<u32>,
}
impl Blocks {
    /// Append one block; blocks must arrive in ascending order.
    pub fn push(&mut self, block: u32, rows: &[(u16, Label)]) -> Result<()> {
        if self.last.is_some_and(|last| last >= block) {
            return Err(crate::Error::Input("Blocks must be pushed in order".into()));
        }
        self.last = Some(block);
        let labels: Vec<_> = rows
            .iter()
            .map(|(_, l)| *l)
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        let width = width(rows.len(), labels.len());
        put(&mut self.directory, u64::from(block), 4);
        put(&mut self.directory, rows.len() as u64, 4);
        put(&mut self.directory, self.keys.len() as u64, 8);
        put(&mut self.directory, width as u64, 4);
        put(
            &mut self.directory,
            if width == 0 { 0 } else { labels.len() as u64 },
            4,
        );
        put(&mut self.directory, self.values.len() as u64, 8);
        put(&mut self.directory, self.dictionary.len() as u64, 8);
        for (key, label) in rows {
            put(&mut self.keys, u64::from(*key), 2);
            if width == 0 {
                label.encode(&mut self.values);
            } else {
                put(
                    &mut self.values,
                    labels
                        .binary_search(label)
                        .map_err(|_| crate::Error::Input("Missing encoded label".into()))?
                        as u64,
                    width,
                );
            }
        }
        if width != 0 {
            for label in labels {
                label.encode(&mut self.dictionary);
            }
        }
        Ok(())
    }
    /// Section bytes accumulated so far.
    #[must_use]
    pub fn len(&self) -> usize {
        self.directory.len() + self.keys.len() + self.values.len() + self.dictionary.len()
    }
    /// True before the first block.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.directory.is_empty()
    }
    /// Encode the shard container.
    pub fn encode(&self) -> Result<Vec<u8>> {
        encode(
            1,
            &[
                (&self.directory, 40),
                (&self.keys, 2),
                (&self.values, 1),
                (&self.dictionary, 20),
            ],
        )
    }
}
/// Encode sorted blocks using a dictionary only when it saves bytes.
pub fn encode_blocks(blocks: &BTreeMap<u32, Vec<(u16, Label)>>) -> Result<Vec<u8>> {
    let mut shard = Blocks::default();
    for (block, rows) in blocks {
        shard.push(*block, rows)?;
    }
    shard.encode()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn labels_do_not_accept_missing_methods_or_reserved_bits() {
        for label in [
            Label([1, 0, 0, 0, 0]),
            Label([0, 0, 0, 8, 0]),
            Label([0, 0, 0, 64, 0]),
            Label([0, 0, 0, 0, 2]),
        ] {
            assert!(label.validate(1, 1).is_err());
        }
        assert!(Label([0; 5]).validate(0, 1).is_ok());
    }
    #[test]
    fn stored_ancestors_cannot_overlap() {
        let root = h3o::LatLng::new(52.0, 4.0)
            .unwrap()
            .to_cell(h3o::Resolution::Three);
        let block = address::address(root).0;
        let bytes = encode_blocks(&BTreeMap::from([(
            block,
            vec![(0, Label([0; 5])), (1, Label([0; 5]))],
        )]))
        .unwrap();
        assert!(decode(bytes, 0, 1).is_err());
    }
    #[test]
    fn block_sizes_predict_incremental_shards() {
        let root = h3o::LatLng::new(52.0, 4.0)
            .unwrap()
            .to_cell(h3o::Resolution::Three);
        let block = address::address(root).0;
        let flat = vec![(1, Label([0; 5])), (2, Label([0, 0, 0, 0, 0]))];
        let coded: Vec<_> = (1..=300)
            .map(|k| (k, Label([0, 0, 0, 0, u32::from(k % 3)])))
            .collect();
        for rows in [vec![], flat, coded] {
            let mut shard = Blocks::default();
            shard.push(block, &rows).unwrap();
            assert_eq!(shard.len(), block_bytes(&rows));
            assert!(shard.push(block, &rows).is_err());
        }
    }
}

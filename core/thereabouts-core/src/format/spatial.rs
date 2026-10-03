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
    pub fn decode(bytes: &[u8], start: usize) -> Result<Self> {
        let mut fields = [0; 5];
        for (i, field) in fields.iter_mut().enumerate() {
            *field = u32::try_from(uint(bytes, start + 4 * i, 4)?).expect("four-byte integer");
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
    pub keys: Vec<u16>,
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
                .map(|i| (*key, self.labels[i]))
        })
    }
}
/// Decode and validate the entire spatial shard, including ancestor disjointness.
#[allow(clippy::many_single_char_names)] // Directory offsets mirror the wire layout.
pub fn decode(bytes: Vec<u8>, places: usize, zones: usize) -> Result<BTreeMap<u32, Block>> {
    let c = Container::decode(bytes, 1, &[40, 2, 1, 20])?;
    let mut blocks = BTreeMap::new();
    let mut ends = [0; 3];
    for row in c.section(0).as_chunks::<40>().0 {
        let b = u32::try_from(uint(row, 0, 4)?).expect("four-byte integer");
        address::cell_at(b, 0)?;
        ensure(
            blocks.last_key_value().is_none_or(|(last, _)| *last < b),
            "Unsorted blocks",
        )?;
        let count = index(uint(row, 4, 4)?)?;
        let k = index(uint(row, 8, 8)?)?;
        let width = index(uint(row, 16, 4)?)?;
        let n = index(uint(row, 20, 4)?)?;
        let v = index(uint(row, 24, 8)?)?;
        let d = index(uint(row, 32, 8)?)?;
        ensure(
            count <= 16807 && width <= 2 && [k, v, d] == ends,
            "Invalid block spans",
        )?;
        ensure(
            if width == 0 {
                n == 0
            } else {
                n > 0 && n <= count && n <= (1 << (8 * width))
            },
            "Invalid dictionary size",
        )?;
        let value_width = if width == 0 { 20 } else { width };
        ends = [k + count * 2, v + count * value_width, d + n * 20];
        ensure(
            (1..=3).all(|i| ends[i - 1] <= c.section(i).len()),
            "Block exceeds sections",
        )?;
        let mut dictionary = Vec::new();
        for i in 0..n {
            let label = Label::decode(c.section(3), d + i * 20)?;
            label.validate(places, zones)?;
            ensure(
                dictionary.last().is_none_or(|last| *last < label),
                "Unsorted label dictionary",
            )?;
            dictionary.push(label);
        }
        let mut keys = Vec::new();
        let mut labels = Vec::new();
        for i in 0..count {
            let key = u16::try_from(uint(c.section(1), k + i * 2, 2)?).expect("two-byte integer");
            let cell = address::cell_at(b, key)?;
            ensure(keys.last().is_none_or(|last| *last < key), "Unsorted keys")?;
            ensure(
                address::ancestors(cell)
                    .iter()
                    .skip(1)
                    .all(|a| keys.binary_search(a).is_err()),
                "Overlapping stored ancestors",
            )?;
            let label = if width == 0 {
                Label::decode(c.section(2), v + i * 20)?
            } else {
                let selector = index(uint(c.section(2), v + i * width, width)?)?;
                ensure(selector < n, "Dangling dictionary selector")?;
                dictionary[selector]
            };
            label.validate(places, zones)?;
            keys.push(key);
            labels.push(label);
        }
        blocks.insert(b, Block { keys, labels });
    }
    ensure(
        (1..=3).all(|i| ends[i - 1] == c.section(i).len()),
        "Unconsumed spatial bytes",
    )?;
    Ok(blocks)
}
/// Encode sorted blocks using a dictionary only when it saves bytes.
pub fn encode_blocks(blocks: &BTreeMap<u32, Vec<(u16, Label)>>) -> Result<Vec<u8>> {
    let (mut directory, mut keys, mut values, mut dictionary) = (vec![], vec![], vec![], vec![]);
    for (block, rows) in blocks {
        let labels: Vec<_> = rows
            .iter()
            .map(|(_, l)| *l)
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        let mut width = if labels.len() <= 256 { 1 } else { 2 };
        if labels.len() * 20 + rows.len() * width >= rows.len() * 20 {
            width = 0;
        }
        put(&mut directory, u64::from(*block), 4);
        put(&mut directory, rows.len() as u64, 4);
        put(&mut directory, keys.len() as u64, 8);
        put(&mut directory, width as u64, 4);
        put(
            &mut directory,
            if width == 0 { 0 } else { labels.len() as u64 },
            4,
        );
        put(&mut directory, values.len() as u64, 8);
        put(&mut directory, dictionary.len() as u64, 8);
        for (key, label) in rows {
            put(&mut keys, u64::from(*key), 2);
            if width == 0 {
                label.encode(&mut values);
            } else {
                put(
                    &mut values,
                    labels.binary_search(label).expect("label was collected") as u64,
                    width,
                );
            }
        }
        if width != 0 {
            for label in labels {
                label.encode(&mut dictionary);
            }
        }
    }
    encode(
        1,
        &[
            (&directory, 40),
            (&keys, 2),
            (&values, 1),
            (&dictionary, 20),
        ],
    )
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
}

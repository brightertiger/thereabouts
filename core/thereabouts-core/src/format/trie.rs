//! Decimal-prefix trie: compact nodes stay resident; selected observations use range reads.
use super::{
    container::{FileShard, encode, put, uint},
    observation::{self, Observation, Strings},
};
use crate::{Error, Result, error::ensure};
use std::{ops::Range, path::Path};
const NONE: u32 = u32::MAX;
#[derive(Debug)]
struct Node {
    children: [u32; 10],
    first: u32,
    count: u32,
}
impl Node {
    fn empty() -> Self {
        Self {
            children: [NONE; 10],
            first: 0,
            count: 0,
        }
    }
}
/// Build a kind-five trie from sorted decimal prefixes; repeated prefixes are candidates.
pub fn encode_entries(entries: &[(String, Observation)]) -> Result<Vec<u8>> {
    ensure(
        entries
            .windows(2)
            .all(|w| w.first().zip(w.get(1)).is_some_and(|(a, b)| a.0 <= b.0)),
        "Unsorted phone prefixes",
    )?;
    let mut nodes = vec![Node::empty()];
    let mut records = Vec::new();
    let mut strings = Strings::new();
    for (row, (key, value)) in entries.iter().enumerate() {
        ensure(valid_prefix(key), "Invalid phone prefix")?;
        let mut node = 0;
        for digit in key.bytes() {
            let slot = usize::from(digit - b'0');
            let next = *nodes
                .get(node)
                .and_then(|n| n.children.get(slot))
                .ok_or_else(|| Error::Corrupt("Missing trie node".into()))?;
            node = if next == NONE {
                let next = u32::try_from(nodes.len())
                    .map_err(|_| Error::Corrupt("Trie exceeds u32".into()))?;
                *nodes
                    .get_mut(node)
                    .and_then(|n| n.children.get_mut(slot))
                    .ok_or_else(|| Error::Corrupt("Missing trie child".into()))? = next;
                nodes.push(Node::empty());
                next as usize
            } else {
                next as usize
            };
        }
        let terminal = nodes
            .get_mut(node)
            .ok_or_else(|| Error::Corrupt("Missing trie terminal".into()))?;
        if terminal.count == 0 {
            terminal.first = u32::try_from(row)
                .map_err(|_| Error::Corrupt("Too many trie observations".into()))?;
        }
        terminal.count = terminal
            .count
            .checked_add(1)
            .ok_or_else(|| Error::Corrupt("Trie count overflow".into()))?;
        observation::encode(value, &mut strings, &mut records)?;
    }
    let mut bytes = Vec::new();
    for node in nodes {
        for v in node.children.into_iter().chain([node.first, node.count]) {
            put(&mut bytes, u64::from(v), 4);
        }
    }
    encode(
        5,
        &[
            (&bytes, 48),
            (&records, 44),
            (&strings.offsets, 8),
            (&strings.bytes, 1),
        ],
    )
}
/// Phone index keys are E.164 digits without the leading plus.
#[must_use]
pub fn valid_prefix(key: &str) -> bool {
    (1..=15).contains(&key.len())
        && !key.starts_with('0')
        && key.bytes().all(|b| b.is_ascii_digit())
}
/// Immutable node directory with an owned shard handle.
#[derive(Debug)]
pub(crate) struct Trie {
    file: FileShard,
    nodes: Vec<Node>,
}
impl Trie {
    pub(crate) fn open(path: &Path) -> Result<Self> {
        let file = FileShard::open(path, 5, &[48, 44, 8, 1])?;
        let bytes = file.section(0)?;
        ensure(!bytes.is_empty(), "Missing trie root")?;
        let mut nodes = Vec::new();
        for row in bytes.as_chunks::<48>().0 {
            let mut children = [NONE; 10];
            for (i, child) in children.iter_mut().enumerate() {
                *child = u32::try_from(uint(row, i * 4, 4)?)
                    .map_err(|_| Error::Corrupt("Trie child overflow".into()))?;
            }
            nodes.push(Node {
                children,
                first: u32::try_from(uint(row, 40, 4)?)
                    .map_err(|_| Error::Corrupt("Trie range overflow".into()))?,
                count: u32::try_from(uint(row, 44, 4)?)
                    .map_err(|_| Error::Corrupt("Trie count overflow".into()))?,
            });
        }
        let trie = Self { file, nodes };
        trie.validate()?;
        Ok(trie)
    }
    fn validate(&self) -> Result<()> {
        let mut seen = vec![0; self.nodes.len()];
        let mut depths = vec![0; self.nodes.len()];
        let mut ranges = Vec::new();
        for (i, node) in self.nodes.iter().enumerate() {
            for &child in &node.children {
                if child == NONE {
                    continue;
                }
                let child = child as usize;
                ensure(child > i && child < self.nodes.len(), "Invalid trie child")?;
                let parent = seen
                    .get_mut(child)
                    .ok_or_else(|| Error::Corrupt("Missing trie parent".into()))?;
                ensure(*parent == 0, "Repeated trie child")?;
                *parent = 1;
                let depth = depths.get(i).copied().unwrap_or(0) + 1;
                ensure(depth <= 15, "Excessive phone prefix length")?;
                *depths
                    .get_mut(child)
                    .ok_or_else(|| Error::Corrupt("Missing trie depth".into()))? = depth;
            }
            ensure(i == 0 || seen.get(i) == Some(&1), "Unreachable trie node")?;
            ensure(i != 0 || node.count == 0, "Root cannot match a phone")?;
            if node.count > 0 {
                ranges.push((u64::from(node.first), u64::from(node.count)));
            }
        }
        ranges.sort_unstable();
        let mut end = 0;
        for (first, count) in ranges {
            ensure(first == end, "Trie observations overlap or have gaps")?;
            end += count;
        }
        ensure(
            end == (self.file.len(1)? / 44) as u64,
            "Trie observation count mismatch",
        )?;
        let null = self.file.range(2, 0, 16)?;
        ensure(null.iter().all(|b| *b == 0), "Invalid null trie string")?;
        let terminal = self.file.range(2, self.file.len(2)? - 8, 8)?;
        ensure(
            uint(&terminal, 0, 8)? == self.file.len(3)? as u64,
            "Invalid trie string terminal",
        )
    }
    pub(crate) fn lookup(&self, key: &str) -> Result<(usize, Range<usize>)> {
        let mut node = 0;
        let mut found = (0, 0..0);
        for (depth, digit) in key.bytes().enumerate() {
            ensure(digit.is_ascii_digit(), "Nondecimal trie query")?;
            let next = *self
                .nodes
                .get(node)
                .and_then(|n| n.children.get(usize::from(digit - b'0')))
                .ok_or_else(|| Error::Corrupt("Missing trie child".into()))?;
            if next == NONE {
                break;
            }
            node = next as usize;
            let value = self
                .nodes
                .get(node)
                .ok_or_else(|| Error::Corrupt("Missing trie node".into()))?;
            if value.count > 0 {
                found = (
                    depth + 1,
                    value.first as usize..value.first as usize + value.count as usize,
                );
            }
        }
        Ok(found)
    }
    pub(crate) fn record(&self, row: usize, count: usize) -> Result<Observation> {
        observation::read(&self.file, 1, row, count)
    }
    pub(crate) fn verify(&self, count: usize) -> Result<()> {
        for row in 0..self.file.len(1)? / 44 {
            self.record(row, count)?;
        }
        Ok(())
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn longest_prefix_and_corrupt_child() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("trie.bin");
        let record = Observation {
            identity: None,
            places: [0; 3],
            latitude: i32::MIN,
            longitude: i32::MIN,
            text: [Some("s".into()), Some("id".into()), None, None, None, None],
        };
        let entries = vec![
            ("1".into(), record.clone()),
            ("1202".into(), record.clone()),
            ("1202".into(), record),
        ];
        let bytes = encode_entries(&entries).unwrap();
        std::fs::write(&path, &bytes).unwrap();
        let trie = Trie::open(&path).unwrap();
        assert_eq!(trie.lookup("12025551234").unwrap(), (4, 1..3));
        assert_eq!(trie.lookup("199").unwrap(), (1, 0..1));
        assert_eq!(trie.lookup("44").unwrap(), (0, 0..0));
        trie.verify(0).unwrap();
        let container =
            super::super::container::Container::decode(bytes, 5, &[48, 44, 8, 1]).unwrap();
        let mut nodes = container.section(0).to_vec();
        nodes[4..8].copy_from_slice(&0_u32.to_le_bytes()); // child back to root
        let corrupt = encode(
            5,
            &[
                (&nodes, 48),
                (container.section(1), 44),
                (container.section(2), 8),
                (container.section(3), 1),
            ],
        )
        .unwrap();
        std::fs::write(&path, corrupt).unwrap();
        assert!(Trie::open(&path).is_err());
    }
}

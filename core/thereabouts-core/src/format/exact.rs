//! Sorted exact-key index: only compact keys are retained; observations are range-read.
use super::{
    container::{FileShard, encode, index, put, uint},
    observation::{self, Observation, Strings},
};
use crate::{Error, Result, error::ensure};
use std::path::Path;
/// An exact-key shard uses kind four and five sections; keys may repeat.
pub fn encode_entries(entries: &[(String, Observation)]) -> Result<Vec<u8>> {
    ensure(
        entries
            .windows(2)
            .all(|w| w.first().zip(w.get(1)).is_some_and(|(a, b)| a.0 <= b.0)),
        "Unsorted exact keys",
    )?;
    let mut offsets = vec![0; 8];
    let mut keys = Vec::new();
    let mut records = Vec::new();
    let mut strings = Strings::new();
    for (key, record) in entries {
        ensure(!key.is_empty(), "Empty exact key")?;
        keys.extend(key.as_bytes());
        put(&mut offsets, keys.len() as u64, 8);
        observation::encode(record, &mut strings, &mut records)?;
    }
    encode(
        4,
        &[
            (&offsets, 8),
            (&keys, 1),
            (&records, 44),
            (&strings.offsets, 8),
            (&strings.bytes, 1),
        ],
    )
}
/// Retained compact key bytes; the owning pack caches decoded observations.
#[derive(Debug)]
pub(crate) struct Exact {
    file: FileShard,
    keys: Vec<u8>,
    offsets: Vec<usize>,
}
impl Exact {
    pub(crate) fn open(path: &Path, reader: &super::reader::Reader) -> Result<Self> {
        let file = FileShard::from_file(reader.open(path)?, 4, &[8, 1, 44, 8, 1])?;
        let bytes = file.section(0)?;
        let keys = file.section(1)?;
        ensure(
            bytes.len() == (file.len(2)? / 44 + 1) * 8,
            "Wrong exact key count",
        )?;
        let offsets = (0..bytes.len())
            .step_by(8)
            .map(|i| index(uint(&bytes, i, 8)?))
            .collect::<Result<Vec<_>>>()?;
        ensure(
            offsets.first() == Some(&0) && offsets.last() == Some(&keys.len()),
            "Invalid exact key bounds",
        )?;
        let mut previous: &[u8] = &[];
        for pair in offsets.windows(2) {
            let (a, b) = pair
                .first()
                .zip(pair.get(1))
                .ok_or_else(|| Error::Corrupt("Missing key bounds".into()))?;
            let key = keys
                .get(*a..*b)
                .filter(|k| !k.is_empty())
                .ok_or_else(|| Error::Corrupt("Invalid key span".into()))?;
            std::str::from_utf8(key).map_err(|_| Error::Corrupt("Invalid key UTF-8".into()))?;
            ensure(previous <= key, "Unsorted exact keys")?;
            previous = key;
        }
        let null = file.range(3, 0, 16)?;
        ensure(null.iter().all(|v| *v == 0), "Invalid null string offset")?;
        let terminal = file.range(3, file.len(3)? - 8, 8)?;
        ensure(
            index(uint(&terminal, 0, 8)?)? == file.len(4)?,
            "Invalid terminal string offset",
        )?;
        Ok(Self {
            file,
            keys,
            offsets,
        })
    }
    fn key(&self, row: usize) -> Result<&[u8]> {
        let (a, b) = self
            .offsets
            .get(row)
            .zip(self.offsets.get(row + 1))
            .ok_or_else(|| Error::Corrupt("Missing key".into()))?;
        self.keys
            .get(*a..*b)
            .ok_or_else(|| Error::Corrupt("Invalid key bounds".into()))
    }
    pub(crate) fn record(&self, row: usize, count: usize) -> Result<Observation> {
        observation::read(&self.file, 2, row, count)
    }
    pub(crate) fn lookup(&self, key: &str) -> Result<Vec<usize>> {
        let mut low = 0;
        let mut high = self.offsets.len() - 1;
        while low < high {
            let mid = low + (high - low) / 2;
            if self.key(mid)? < key.as_bytes() {
                low = mid + 1;
            } else {
                high = mid;
            }
        }
        let mut values = Vec::new();
        while low + 1 < self.offsets.len() && self.key(low)? == key.as_bytes() {
            values.push(low);
            low += 1;
        }
        Ok(values)
    }
    pub(crate) fn verify(&self, count: usize) -> Result<()> {
        for i in 0..self.offsets.len() - 1 {
            observation::read(&self.file, 2, i, count)?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn duplicate_keys_and_null_source_points_round_trip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("exact.bin");
        let record = Observation {
            fallback: [None, None, None, None],
            identity: None,
            places: [0; 3],
            latitude: i32::MIN,
            longitude: i32::MIN,
            text: [
                Some("source".into()),
                Some("id".into()),
                Some("東京".into()),
                Some("00100".into()),
                None,
                None,
            ],
        };
        let entries = vec![
            ("AA\\0".to_owned() + "00100", record.clone()),
            ("AA\\0".to_owned() + "00100", record),
        ];
        std::fs::write(&path, encode_entries(&entries).unwrap()).unwrap();
        let shard =
            Exact::open(&path, &super::super::reader::Reader::native(Path::new(""))).unwrap();
        assert_eq!(shard.lookup("AA\\000100").unwrap(), vec![0, 1]);
        assert_eq!(shard.lookup("AA\\0100").unwrap(), Vec::<usize>::new());
        let decoded = shard.record(1, 0).unwrap();
        assert_eq!(decoded.text[2].as_deref(), Some("東京"));
        assert!(decoded.point().is_none());
        shard.verify(0).unwrap();
    }
}

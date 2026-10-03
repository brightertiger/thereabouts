//! Name FSTs and trigram postings share one record layout between export and lookup.
use super::{
    container::{FileShard, encode, index, put, uint},
    observation::{self, Strings},
};
use crate::{Error, Result, error::ensure, name_normalization::trigrams};
use fst::{IntoStreamer, Streamer};
use std::{collections::BTreeMap, path::Path};
/// One published canonical-city spelling; keys are normalized separately.
#[derive(Clone, Debug)]
pub struct Entry {
    /// Country, state and canonical-city references.
    pub places: [u32; 3],
    /// Source name, without normalization.
    pub name: String,
    /// English/alternate versus primary spelling.
    pub alternate: bool,
}
#[allow(clippy::needless_pass_by_value)] // Result::map_err consumes its error adapter.
fn fst_error(error: fst::Error) -> Error {
    Error::Corrupt(format!("Invalid name FST: {error}"))
}
/// Encode sorted keys, shared spelling records and a Unicode trigram posting index.
pub fn encode_entries(entries: &[(String, Entry)]) -> Result<Vec<u8>> {
    let mut keys = Vec::<(String, u64)>::new();
    let mut offsets = Vec::new();
    let mut records = Vec::new();
    let mut strings = Strings::new();
    for (row, (key, entry)) in entries.iter().enumerate() {
        ensure(
            !key.is_empty() && key.chars().count() <= 128,
            "Invalid normalized name length",
        )?;
        if keys.last().is_none_or(|(previous, _)| previous != key) {
            ensure(
                keys.last().is_none_or(|(p, _)| p < key),
                "Unsorted name keys",
            )?;
            put(&mut offsets, row as u64, 8);
            keys.push((key.clone(), keys.len() as u64));
        }
        for reference in entry.places {
            put(&mut records, u64::from(reference), 4);
        }
        put(
            &mut records,
            u64::from(strings.reference(Some(&entry.name))?),
            4,
        );
        put(&mut records, u64::from(entry.alternate), 4);
    }
    put(&mut offsets, entries.len() as u64, 8);
    let mut grams = BTreeMap::<String, Vec<u64>>::new();
    for (key, id) in &keys {
        for gram in trigrams(key) {
            grams.entry(gram).or_default().push(*id);
        }
    }
    let mut gram_offsets = vec![0; 8];
    let mut postings = Vec::new();
    for rows in grams.values() {
        for row in rows {
            ensure(u32::try_from(*row).is_ok(), "Too many name keys")?;
            put(&mut postings, *row, 4);
        }
        put(&mut gram_offsets, (postings.len() / 4) as u64, 8);
    }
    let map = fst::Map::from_iter(keys.iter().map(|(k, v)| (k, *v))).map_err(fst_error)?;
    let gram_map = fst::Map::from_iter(grams.keys().enumerate().map(|(i, k)| (k, i as u64)))
        .map_err(fst_error)?;
    encode(
        8,
        &[
            (map.as_fst().as_bytes(), 1),
            (&offsets, 8),
            (&records, 20),
            (&strings.offsets, 8),
            (&strings.bytes, 1),
            (gram_map.as_fst().as_bytes(), 1),
            (&gram_offsets, 8),
            (&postings, 4),
        ],
    )
}
/// Resident search directories; source-name strings are range-read when requested.
#[derive(Debug)]
pub(crate) struct Names {
    file: FileShard,
    map: fst::Map<Vec<u8>>,
    grams: fst::Map<Vec<u8>>,
    keys: Vec<String>,
    gram_counts: Vec<usize>,
    lengths: Vec<usize>,
    offsets: Vec<usize>,
    gram_offsets: Vec<usize>,
    postings: Vec<usize>,
    records: Vec<[u32; 5]>,
}
fn decode_offsets(bytes: &[u8], count: usize, end: usize) -> Result<Vec<usize>> {
    let values = bytes
        .as_chunks::<8>()
        .0
        .iter()
        .map(|row| index(u64::from_le_bytes(*row)))
        .collect::<Result<Vec<_>>>()?;
    ensure(
        values.len() == count + 1
            && values.first() == Some(&0)
            && values.last() == Some(&end)
            && values.windows(2).all(|w| w.first() < w.get(1)),
        "Invalid name directory",
    )?;
    Ok(values)
}
impl Names {
    pub(crate) fn open(path: &Path) -> Result<Self> {
        // The fst crate documents panic on malformed serialized nodes. Validate
        // the full DAG at admission and convert that boundary to a coded error.
        std::panic::catch_unwind(|| Self::read(path))
            .map_err(|_| Error::Corrupt("Malformed serialized name FST".into()))?
    }
    fn read(path: &Path) -> Result<Self> {
        let file = FileShard::open(path, 8, &[1, 8, 20, 8, 1, 1, 8, 4])?;
        let map = super::fst::read(file.section(0)?, true)?;
        let grams = super::fst::read(file.section(5)?, true)?;
        ensure(
            map.len() <= 1_000_000 && grams.len() <= 4_000_000,
            "Oversized name FST",
        )?;
        let mut keys = Vec::new();
        let mut stream = map.stream();
        while let Some((key, id)) = stream.next() {
            ensure(id == keys.len() as u64, "Unordered name key identifiers")?;
            let key = std::str::from_utf8(key)
                .map_err(|_| Error::Corrupt("Invalid name key UTF-8".into()))?;
            ensure(
                !key.is_empty() && key.chars().count() <= 128,
                "Invalid name key length",
            )?;
            ensure(keys.len() < 1_000_000, "Excessive name keys")?;
            keys.push(key.to_owned());
        }
        ensure(keys.len() == map.len(), "Incorrect name FST key count")?;
        let mut records = Vec::new();
        for row in file.section(2)?.as_chunks::<20>().0 {
            let mut record = [0; 5];
            for (i, value) in record.iter_mut().enumerate() {
                *value = u32::try_from(uint(row, i * 4, 4)?)
                    .map_err(|_| Error::Corrupt("Name reference overflow".into()))?;
            }
            records.push(record);
        }
        let offsets = decode_offsets(&file.section(1)?, map.len(), records.len())?;
        let postings = file
            .section(7)?
            .as_chunks::<4>()
            .0
            .iter()
            .map(|b| u32::from_le_bytes(*b) as usize)
            .collect::<Vec<_>>();
        ensure(
            postings.iter().all(|id| *id < keys.len()),
            "Dangling trigram name",
        )?;
        let gram_offsets = decode_offsets(&file.section(6)?, grams.len(), postings.len())?;
        let null = file.range(3, 0, 16)?;
        ensure(null.iter().all(|v| *v == 0), "Invalid name null string")?;
        let terminal = file.range(3, file.len(3)? - 8, 8)?;
        ensure(
            uint(&terminal, 0, 8)? == file.len(4)? as u64,
            "Invalid name string terminal",
        )?;
        Ok(Self {
            file,
            map,
            grams,
            gram_counts: keys.iter().map(|key| trigrams(key).len()).collect(),
            lengths: keys.iter().map(|key| key.chars().count()).collect(),
            keys,
            offsets,
            gram_offsets,
            postings,
            records,
        })
    }
    fn rows(&self, id: u64) -> Result<std::ops::Range<usize>> {
        let id = index(id)?;
        let (first, last) = self
            .offsets
            .get(id)
            .zip(self.offsets.get(id + 1))
            .ok_or_else(|| Error::Corrupt("Invalid name row span".into()))?;
        Ok(*first..*last)
    }
    pub(crate) fn exact(&self, key: &str) -> Result<Vec<usize>> {
        self.map
            .get(key)
            .map_or_else(|| Ok(vec![]), |id| Ok(self.rows(id)?.collect()))
    }
    pub(crate) fn prefix(&self, key: &str) -> Result<Vec<usize>> {
        let mut stream = self.map.range().ge(key).into_stream();
        let mut rows = Vec::new();
        while let Some((found, id)) = stream.next() {
            if !found.starts_with(key.as_bytes()) {
                break;
            }
            rows.extend(self.rows(id)?);
        }
        Ok(rows)
    }
    pub(crate) fn fuzzy(&self, key: &str) -> Result<Vec<usize>> {
        let query = trigrams(key);
        let distance = crate::name_distance::Distance::new(key);
        let mut touched = Vec::new();
        // At most 9 MB per million admitted keys: byte counters and touched IDs.
        // No tree allocation per posting or scan over unvisited keys.
        // Counts cannot exceed 128 unique query trigrams. Full counting preserves
        // hard-filter/population semantics instead of truncating common-gram hits.
        let mut counts = vec![0_u8; self.keys.len()];
        let length = key.chars().count();
        let edits = (length / 4).clamp(1, 3);
        for gram in &query {
            if let Some(id) = self.grams.get(gram) {
                let id = index(id)?;
                let (a, b) = self
                    .gram_offsets
                    .get(id)
                    .zip(self.gram_offsets.get(id + 1))
                    .ok_or_else(|| Error::Corrupt("Invalid trigram span".into()))?;
                for id in self
                    .postings
                    .get(*a..*b)
                    .ok_or_else(|| Error::Corrupt("Invalid trigram postings".into()))?
                {
                    if let Some(count) = counts.get_mut(*id) {
                        if *count == 0 {
                            touched.push(*id);
                        }
                        *count = count.saturating_add(1);
                    }
                }
            }
        }
        let mut rows = Vec::new();
        // Only visited keys need testing; common postings are already sorted.
        touched.sort_unstable();
        for id in touched {
            let common = usize::from(counts.get(id).copied().unwrap_or(0));
            let required = ((query.len() + self.gram_counts.get(id).copied().unwrap_or(128)) * 45)
                .div_ceil(200);
            if common < required
                || self
                    .lengths
                    .get(id)
                    .is_none_or(|n| n.abs_diff(length) > edits)
            {
                continue;
            }
            let name = self
                .keys
                .get(id)
                .ok_or_else(|| Error::Corrupt("Missing name key".into()))?;
            // Dice >= 0.45, then at most three edits; integer math avoids unstable score ties.
            if distance.close(name) {
                rows.extend(self.rows(id as u64)?);
            }
        }
        Ok(rows)
    }
    pub(crate) fn record(&self, row: usize, count: usize) -> Result<([u32; 3], bool)> {
        let record = self
            .records
            .get(row)
            .ok_or_else(|| Error::Corrupt("Missing name record".into()))?;
        let [country, state, city, _, kind] = *record;
        ensure(
            city != 0
                && country != 0
                && [country, state, city].iter().all(|v| *v as usize <= count)
                && kind <= 1,
            "Invalid name catalogue reference",
        )?;
        Ok(([country, state, city], kind == 1))
    }
    pub(crate) fn spelling(&self, row: usize) -> Result<String> {
        let reference = self
            .records
            .get(row)
            .and_then(|r| r.get(3))
            .ok_or_else(|| Error::Corrupt("Missing spelling reference".into()))?;
        observation::string(&self.file, 3, u64::from(*reference))?
            .ok_or_else(|| Error::Corrupt("Missing source spelling".into()))
    }
    pub(crate) fn verify(&self, count: usize) -> Result<()> {
        for row in 0..self.records.len() {
            self.record(row, count)?;
            self.spelling(row)?;
        }
        let expected_postings: usize = self.keys.iter().map(|key| trigrams(key).len()).sum();
        ensure(
            self.postings.len() == expected_postings,
            "Incomplete name trigram index",
        )?;
        let mut stream = self.grams.stream();
        let mut ordinal = 0;
        while let Some((gram, id)) = stream.next() {
            ensure(id == ordinal, "Unordered trigram identifiers")?;
            ordinal += 1;
            let gram = std::str::from_utf8(gram)
                .map_err(|_| Error::Corrupt("Invalid trigram UTF-8".into()))?;
            ensure(gram.chars().count() == 3, "Invalid name trigram")?;
            let id = index(id)?;
            let (a, b) = self
                .gram_offsets
                .get(id)
                .zip(self.gram_offsets.get(id + 1))
                .ok_or_else(|| Error::Corrupt("Missing trigram directory".into()))?;
            let postings = self
                .postings
                .get(*a..*b)
                .ok_or_else(|| Error::Corrupt("Invalid trigram range".into()))?;
            ensure(
                postings.windows(2).all(|w| w.first() < w.get(1)),
                "Unsorted trigram postings",
            )?;
            for key in postings {
                ensure(
                    self.keys
                        .get(*key)
                        .is_some_and(|k| trigrams(k).contains(gram)),
                    "Incorrect name trigram",
                )?;
            }
        }
        ensure(
            ordinal == self.grams.len() as u64,
            "Incorrect trigram FST key count",
        )?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::name_normalization::close;
    use proptest::prelude::*;
    proptest! {
        #[test]
        fn fuzzy_agrees_with_exhaustive_dice_and_edit_distance(
            values in proptest::collection::btree_set("[a-z]{3,18}", 1..40), query in "[a-z]{3,18}"
        ) {
            let dir=tempfile::tempdir().unwrap(); let path=dir.path().join("names.bin");
            let entries=values.into_iter().map(|name|(name.clone(),Entry{places:[1,0,2],name,alternate:false})).collect::<Vec<_>>();
            std::fs::write(&path,encode_entries(&entries).unwrap()).unwrap();
            let index=Names::open(&path).unwrap();
            let grams=trigrams(&query);
            let expected=entries.iter().enumerate().filter_map(|(row,(name,_))| {
                let other=trigrams(name);
                (grams.intersection(&other).count()*200 >= (grams.len()+other.len())*45 && close(&query,name)).then_some(row)
            }).collect::<Vec<_>>();
            prop_assert_eq!(index.fuzzy(&query).unwrap(),expected);
        }

        #[test]
        fn round_trip_and_corrupt_fst(name in "[a-z]{2,24}") {
            let dir=tempfile::tempdir().unwrap();let path=dir.path().join("names.bin");
            let entries=vec![(name.clone(),Entry{places:[1,0,2],name:name.clone(),alternate:false})];
            let bytes=encode_entries(&entries).unwrap();
            std::fs::write(&path,&bytes).unwrap();
            let index=Names::open(&path).unwrap();
            prop_assert_eq!(index.exact(&name).unwrap(),vec![0]);
            prop_assert_eq!(index.record(0,2).unwrap(),([1,0,2],false));
            prop_assert_eq!(index.spelling(0).unwrap(),name);
            index.verify(2).unwrap();
            let c=super::super::container::Container::decode(bytes,8,&[1,8,20,8,1,1,8,4]).unwrap();
            let mut fst=c.section(0).to_vec();
            // Change the FST payload while preserving the outer container structure.
            fst[16]^=1;
            let corrupt=encode(8,&[(&fst,1),(c.section(1),8),(c.section(2),20),(c.section(3),8),(c.section(4),1),(c.section(5),1),(c.section(6),8),(c.section(7),4)]).unwrap();
            std::fs::write(&path,corrupt).unwrap();
            prop_assert!(Names::open(&path).is_err());
        }
    }
}

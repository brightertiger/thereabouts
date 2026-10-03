//! Lazy core-pack ownership. No lookup reads outside its inventoried shards.
use super::{
    cache::Cache,
    catalogue::{self, Place},
    container::{Container, FileShard},
    manifest::{self, Manifest},
    metadata::Metadata,
    metadata_index::MetadataIndex,
    spatial::{self, Block, Entry},
};
use crate::{Error, Result, error::ensure};
use std::{
    collections::BTreeMap,
    fs,
    path::Path,
    sync::{Arc, Mutex},
};

/// Retained decoded blocks: 8 MiB accommodates the sample's 133k sparse labels.
/// Eviction is by allocated vector bytes; active readers may retain an evicted Arc.
pub const BLOCK_CACHE_BYTES: usize = 8 * 1024 * 1024;
/// Four MiB for repeatedly projected places; charged by owned string capacities.
/// The sample's hot workload touches tens of places; random queries exercise eviction.
pub const PLACE_CACHE_BYTES: usize = 4 * 1024 * 1024;

#[derive(Debug)]
struct BlockSource {
    shard: Arc<FileShard>,
    entry: Entry,
}
#[derive(Debug)]
struct CatalogueSource {
    first: usize,
    end: usize,
    shard: FileShard,
}
/// Concurrent pack handle. Open checks inventories; lookups validate accessed payloads.
#[derive(Debug)]
pub struct Pack {
    /// Validated release identity and policy used when projecting results.
    pub manifest: Manifest,
    /// Published side-table rows; runtime indexes refer to these rows.
    pub metadata: Metadata,
    pub(crate) metadata_index: MetadataIndex,
    blocks: BTreeMap<u32, BlockSource>,
    catalogues: Vec<CatalogueSource>,
    pub(crate) place_count: usize,
    pub(crate) exacts: Vec<super::exact::Exact>,
    pub(crate) tries: Vec<super::trie::Trie>,
    block_cache: Mutex<Cache<u32, Block>>,
    place_cache: Mutex<Cache<u32, Place>>,
    observation_cache: Mutex<Cache<(usize, usize), super::observation::Observation>>,
}
impl Pack {
    /// Read headers/directories only; opt in to full hashes and structural verification.
    pub fn open(root: &Path, verify: bool) -> Result<Self> {
        let manifest = if verify {
            super::verify::verify(root)?
        } else {
            manifest::read(root)?
        };
        let mut metadata = None;
        let mut exacts = Vec::new();
        let mut tries = Vec::new();
        let mut catalogues = Vec::new();
        let mut place_count = 0_usize;
        let mut blocks = BTreeMap::new();
        for file in &manifest.files {
            let path = manifest::artifact_path(root, &file.path)?;
            match file.kind.as_str() {
                "catalogue" => {
                    let shard = FileShard::open(&path, 2, &[80, 8, 1])?;
                    catalogue::validate_header(&shard)?;
                    let end = place_count
                        .checked_add(shard.len(0)? / 80)
                        .ok_or_else(|| Error::Corrupt("Catalogue count overflow".into()))?;
                    ensure(
                        u32::try_from(end).is_ok(),
                        "Catalogue exceeds u32 references",
                    )?;
                    catalogues.push(CatalogueSource {
                        first: place_count,
                        end,
                        shard,
                    });
                    place_count = end;
                }
                "metadata" => {
                    ensure(metadata.is_none(), "Repeated metadata table")?;
                    let c = Container::decode(fs::read(path)?, 3, &[1])?;
                    metadata = Some(serde_json::from_slice::<Metadata>(c.section(0))?);
                }
                "cells" => {
                    let shard = Arc::new(FileShard::open(&path, 1, &[40, 2, 1, 20])?);
                    let entries = spatial::directory(
                        &shard.section(0)?,
                        [shard.len(1)?, shard.len(2)?, shard.len(3)?],
                    )?;
                    for entry in entries {
                        ensure(
                            blocks
                                .insert(
                                    entry.block,
                                    BlockSource {
                                        shard: Arc::clone(&shard),
                                        entry,
                                    },
                                )
                                .is_none(),
                            "Repeated spatial block",
                        )?;
                    }
                }
                "exact" => exacts.push(super::exact::Exact::open(&path)?),
                "trie" => tries.push(super::trie::Trie::open(&path)?),
                "notice" => {}
                _ => return Err(Error::Incompatible("Unknown artifact kind".into())),
            }
        }
        ensure(
            match manifest.family.as_str() {
                "core" => true,
                "phone" => !tries.is_empty(),
                _ => !exacts.is_empty(),
            },
            "Missing required exact index",
        )?;
        let metadata = metadata.ok_or_else(|| Error::Corrupt("Missing metadata table".into()))?;
        metadata.validate()?;
        let metadata_index = MetadataIndex::build(&metadata)?;
        Ok(Self {
            manifest,
            metadata,
            metadata_index,
            blocks,
            catalogues,
            place_count,
            exacts,
            tries,
            block_cache: Mutex::new(Cache::new(BLOCK_CACHE_BYTES)),
            place_cache: Mutex::new(Cache::new(PLACE_CACHE_BYTES)),
            observation_cache: Mutex::new(Cache::new(PLACE_CACHE_BYTES)),
        })
    }
    pub(crate) fn prefix_observations(
        &self,
        key: &str,
    ) -> Result<Vec<Arc<super::observation::Observation>>> {
        let mut longest = 0;
        let mut selected = Vec::new();
        for (i, shard) in self.tries.iter().enumerate() {
            let (length, rows) = shard.lookup(key)?;
            if length > longest {
                longest = length;
                selected.clear();
            }
            if length == longest {
                selected.extend(rows.map(|row| (i, row)));
            }
        }
        selected
            .into_iter()
            .map(|(i, row)| {
                let shard = self
                    .tries
                    .get(i)
                    .ok_or_else(|| Error::Corrupt("Missing trie".into()))?;
                self.cached_observation((self.exacts.len() + i, row), || {
                    shard.record(row, self.place_count)
                })
            })
            .collect()
    }
    fn cached_observation(
        &self,
        key: (usize, usize),
        read: impl FnOnce() -> Result<super::observation::Observation>,
    ) -> Result<Arc<super::observation::Observation>> {
        let cached = self
            .observation_cache
            .lock()
            .map_err(|_| Error::Corrupt("Poisoned observation cache".into()))?
            .get(key);
        if let Some(value) = cached {
            return Ok(value);
        }
        let value = read()?;
        let bytes = size_of::<super::observation::Observation>()
            + value
                .text
                .iter()
                .flatten()
                .map(String::capacity)
                .sum::<usize>();
        Ok(self
            .observation_cache
            .lock()
            .map_err(|_| Error::Corrupt("Poisoned observation cache".into()))?
            .insert(key, value, bytes))
    }
    pub(crate) fn observations(
        &self,
        key: &str,
    ) -> Result<Vec<Arc<super::observation::Observation>>> {
        let mut records = Vec::new();
        for (i, shard) in self.exacts.iter().enumerate() {
            for row in shard.lookup(key)? {
                records.push(
                    self.cached_observation((i, row), || shard.record(row, self.place_count))?,
                );
            }
        }
        Ok(records)
    }
    pub(crate) fn block(&self, block: u32) -> Result<Option<Arc<Block>>> {
        let Some(source) = self.blocks.get(&block) else {
            return Ok(None);
        };
        let mut cache = self
            .block_cache
            .lock()
            .map_err(|_| Error::Corrupt("Poisoned block cache".into()))?;
        if let Some(value) = cache.get(block) {
            return Ok(Some(value));
        }
        drop(cache);
        let mut spans: [Vec<u8>; 3] = std::array::from_fn(|_| Vec::new());
        for (section, &(offset, length)) in source.entry.spans.iter().enumerate() {
            if let Some(span) = spans.get_mut(section) {
                *span = source.shard.range(section + 1, offset, length)?;
            }
        }
        let value = spatial::decode_block(
            &source.entry,
            &spans[0],
            &spans[1],
            &spans[2],
            self.place_count,
            self.metadata.timezone_sets.len(),
        )?;
        let bytes = value.keys.capacity() * size_of::<u16>()
            + value.labels.capacity() * size_of::<spatial::Label>();
        let mut cache = self
            .block_cache
            .lock()
            .map_err(|_| Error::Corrupt("Poisoned block cache".into()))?;
        Ok(Some(cache.insert(block, value, bytes)))
    }
    /// Reference zero is null; other references decode and validate one raw record.
    pub fn place(&self, reference: u32) -> Result<Option<Arc<Place>>> {
        let Some(index) = reference.checked_sub(1).map(|v| v as usize) else {
            return Ok(None);
        };
        let mut places = self
            .place_cache
            .lock()
            .map_err(|_| Error::Corrupt("Poisoned place cache".into()))?;
        if let Some(place) = places.get(reference) {
            return Ok(Some(place));
        }
        drop(places);
        let shard_index = self.catalogues.partition_point(|s| s.end <= index);
        let source = self
            .catalogues
            .get(shard_index)
            .ok_or_else(|| Error::Corrupt("Dangling place reference".into()))?;
        let place = catalogue::read_place(&source.shard, index - source.first)?;
        place.validate(self.place_count)?;
        let bytes = size_of::<Place>()
            + place
                .text
                .iter()
                .chain(std::iter::once(&place.timezone))
                .filter_map(Option::as_ref)
                .map(String::capacity)
                .sum::<usize>();
        let mut places = self
            .place_cache
            .lock()
            .map_err(|_| Error::Corrupt("Poisoned place cache".into()))?;
        Ok(Some(places.insert(reference, place, bytes)))
    }
}

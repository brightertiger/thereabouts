//! Lazy core-pack ownership. No lookup reads outside its inventoried shards.
use super::{
    cache::Cache,
    catalogue::{Catalogue, Place},
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
/// Retained raw catalogue bytes: four nominal 4 MiB writer shards, not decoded places.
pub const CATALOGUE_CACHE_BYTES: usize = 16 * 1024 * 1024;
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
    place_count: usize,
    block_cache: Mutex<Cache<u32, Block>>,
    catalogue_cache: Mutex<Cache<usize, Catalogue>>,
    place_cache: Mutex<Cache<u32, Place>>,
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
        let mut catalogues = Vec::new();
        let mut place_count = 0_usize;
        let mut blocks = BTreeMap::new();
        for file in &manifest.files {
            let path = manifest::artifact_path(root, &file.path)?;
            match file.kind.as_str() {
                "catalogue" => {
                    let shard = FileShard::open(&path, 2, &[80, 8, 1])?;
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
                "notice" => {}
                _ => return Err(Error::Incompatible("Unknown artifact kind".into())),
            }
        }
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
            block_cache: Mutex::new(Cache::new(BLOCK_CACHE_BYTES)),
            catalogue_cache: Mutex::new(Cache::new(CATALOGUE_CACHE_BYTES)),
            place_cache: Mutex::new(Cache::new(PLACE_CACHE_BYTES)),
        })
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
        let shard_index = self.catalogues.partition_point(|s| s.end <= index);
        let source = self
            .catalogues
            .get(shard_index)
            .ok_or_else(|| Error::Corrupt("Dangling place reference".into()))?;
        let catalogue = {
            let mut cache = self
                .catalogue_cache
                .lock()
                .map_err(|_| Error::Corrupt("Poisoned catalogue cache".into()))?;
            if let Some(value) = cache.get(shard_index) {
                value
            } else {
                let value = Catalogue::decode(source.shard.all()?)?;
                let bytes = value.bytes();
                cache.insert(shard_index, value, bytes)
            }
        };
        let place = catalogue.place(index - source.first)?;
        place.validate(self.place_count)?;
        let bytes = size_of::<Place>()
            + place
                .text
                .iter()
                .chain(std::iter::once(&place.timezone))
                .filter_map(Option::as_ref)
                .map(String::capacity)
                .sum::<usize>();
        Ok(Some(places.insert(reference, place, bytes)))
    }
}

//! Validated core-pack ownership. No lookup reads outside its inventory.
use super::metadata::Metadata;
use super::{
    catalogue::{self, Place},
    container::Container,
    manifest::{self, Manifest},
    spatial::{self, Block},
};
use crate::{Result, error::ensure};
use std::{collections::BTreeMap, fs, path::Path};

/// Fully checked pack, reusable concurrently by scalar and batch callers.
#[derive(Debug)]
pub struct Pack {
    pub manifest: Manifest,
    pub places: Vec<Place>,
    pub blocks: BTreeMap<u32, Block>,
    pub metadata: Metadata,
}
impl Pack {
    /// Opening verifies hashes and structural invariants once, before answering.
    pub fn open(root: &Path) -> Result<Self> {
        let manifest = manifest::read(root)?;
        manifest::verify(root, &manifest)?;
        let mut places = vec![];
        let mut metadata = None;
        for file in &manifest.files {
            let path = manifest::artifact_path(root, &file.path)?;
            match file.kind.as_str() {
                "catalogue" => places.extend(catalogue::decode(fs::read(path)?)?),
                "metadata" => {
                    ensure(metadata.is_none(), "Repeated metadata table")?;
                    let c = Container::decode(fs::read(path)?, 3, &[1])?;
                    metadata = Some(serde_json::from_slice::<Metadata>(c.section(0))?);
                }
                "cells" | "notice" => {}
                _ => return Err(crate::Error::Incompatible("Unknown artifact kind".into())),
            }
        }
        let metadata =
            metadata.ok_or_else(|| crate::Error::Corrupt("Missing metadata table".into()))?;
        metadata.validate()?;
        ensure(
            places.windows(2).all(|p| p[0].field(0) < p[1].field(0)),
            "Unsorted public place IDs",
        )?;
        for place in &places {
            place.validate(places.len())?;
        }
        let mut blocks = BTreeMap::new();
        for file in &manifest.files {
            if file.kind == "cells" {
                for (id, block) in spatial::decode(
                    fs::read(manifest::artifact_path(root, &file.path)?)?,
                    places.len(),
                    metadata.timezone_sets.len(),
                )? {
                    ensure(blocks.insert(id, block).is_none(), "Repeated spatial block")?;
                }
            }
        }
        Ok(Self {
            manifest,
            places,
            blocks,
            metadata,
        })
    }
    /// Reference zero is null; other references were checked on open.
    #[must_use]
    pub fn place(&self, reference: u32) -> Option<&Place> {
        reference
            .checked_sub(1)
            .and_then(|i| self.places.get(i as usize))
    }
}

//! Full verification retains at most one shard's decoded records at a time.
use super::{
    catalogue,
    container::Container,
    manifest::{self, Manifest},
    metadata::Metadata,
    spatial,
};
use crate::{Error, Result, error::ensure};
use std::{collections::BTreeSet, fs, path::Path};

/// Hash and structurally validate a pack without loading the world's cell index.
pub fn verify(root: &Path) -> Result<Manifest> {
    let manifest = manifest::read(root)?;
    manifest::verify(root, &manifest)?;
    let mut metadata = None;
    let mut total = 0_usize;
    for file in &manifest.files {
        let path = manifest::artifact_path(root, &file.path)?;
        match file.kind.as_str() {
            "metadata" => {
                ensure(metadata.is_none(), "Repeated metadata table")?;
                let c = Container::decode(fs::read(path)?, 3, &[1])?;
                metadata = Some(serde_json::from_slice::<Metadata>(c.section(0))?);
            }
            "catalogue" => {
                let container = Container::decode(fs::read(path)?, 2, &[80, 8, 1])?;
                total = total
                    .checked_add(container.section(0).len() / 80)
                    .ok_or_else(|| Error::Corrupt("Catalogue count overflow".into()))?;
                ensure(
                    u32::try_from(total).is_ok(),
                    "Catalogue exceeds u32 references",
                )?;
            }
            "cells" | "notice" => {}
            _ => return Err(Error::Incompatible("Unknown artifact kind".into())),
        }
    }
    let metadata = metadata.ok_or_else(|| Error::Corrupt("Missing metadata".into()))?;
    metadata.validate()?;
    let mut blocks = BTreeSet::new();
    let mut previous_id = None;
    for file in &manifest.files {
        let path = manifest::artifact_path(root, &file.path)?;
        match file.kind.as_str() {
            "catalogue" => {
                for place in catalogue::decode(fs::read(path)?)? {
                    place.validate(total)?;
                    ensure(
                        previous_id
                            .as_ref()
                            .is_none_or(|last: &String| last.as_str() < place.field(0)),
                        "Unsorted public place IDs",
                    )?;
                    previous_id = Some(place.field(0).to_owned());
                }
            }
            "cells" => {
                for (id, _) in
                    spatial::decode(fs::read(path)?, total, metadata.timezone_sets.len())?
                {
                    ensure(blocks.insert(id), "Repeated spatial block")?;
                }
            }
            _ => {}
        }
    }
    Ok(manifest)
}

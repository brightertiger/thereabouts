//! Full verification retains at most one shard's decoded records at a time.
use super::{
    catalogue,
    container::Container,
    manifest::{self, Manifest},
    metadata::Metadata,
    spatial,
};
use crate::{Error, Result, error::ensure};
use std::{collections::BTreeSet, path::Path};

/// Hash and structurally validate a pack without loading the world's cell index.
pub fn verify(root: &Path) -> Result<Manifest> {
    if !root.exists() {
        return Err(Error::PackNotFound(root.to_owned()));
    }
    verify_with(&super::reader::Reader::native(root))
}
/// Validate byte identity and all structure through a supplied host file source.
pub fn verify_with(root: &super::reader::Reader<'_>) -> Result<Manifest> {
    let manifest = manifest::read_with(root)?;
    manifest::verify_with(root, &manifest)?;
    ensure(
        manifest.family == "core"
            || manifest.forward_columns.is_some()
            || manifest.plate_columns.is_some()
            || manifest.files.iter().any(|f| {
                f.kind
                    == match manifest.family.as_str() {
                        "phone" => "trie",
                        "ip" => "intervals",
                        "plates" => "plates",
                        _ => "exact",
                    }
            }),
        "Missing required exact index",
    )?;
    let mut metadata = None;
    let mut total = 0_usize;
    for file in &manifest.files {
        let path = manifest::artifact_path(root, &file.path)?;
        match file.kind.as_str() {
            "metadata" => {
                ensure(metadata.is_none(), "Repeated metadata table")?;
                let c = Container::decode(root.read(&path)?, 3, &[1])?;
                metadata = Some(serde_json::from_slice::<Metadata>(c.section(0))?);
            }
            "catalogue" => {
                let container = Container::decode(root.read(&path)?, 2, &[80, 8, 1])?;
                total = total
                    .checked_add(container.section(0).len() / 80)
                    .ok_or_else(|| Error::Corrupt("Catalogue count overflow".into()))?;
                ensure(
                    u32::try_from(total).is_ok(),
                    "Catalogue exceeds u32 references",
                )?;
            }
            "cells" | "exact" | "trie" | "intervals" | "plates" | "names" | "notice" | "keys" => {}
            role if super::compact::ROLES.contains(&role)
                || super::plate_columns::ROLES.contains(&role) => {}
            _ => return Err(Error::Incompatible("Unknown artifact kind".into())),
        }
    }
    let metadata = metadata.ok_or_else(|| Error::Corrupt("Missing metadata".into()))?;
    metadata.validate()?;
    super::metadata_index::MetadataIndex::build(&metadata)?;
    let mut blocks = BTreeSet::new();
    let mut previous_id = None;
    let mut previous_range = None;
    for file in &manifest.files {
        let path = manifest::artifact_path(root, &file.path)?;
        match file.kind.as_str() {
            "catalogue" => {
                for place in catalogue::decode(root.read(&path)?)? {
                    place.validate(total)?;
                    ensure(
                        manifest.family != "core" || !place.field(11).is_empty(),
                        "Missing core catalogue evidence",
                    )?;
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
                    spatial::decode(root.read(&path)?, total, metadata.timezone_sets.len())?
                {
                    ensure(blocks.insert(id), "Repeated spatial block")?;
                }
            }
            "exact" => super::exact::Exact::open(&path, root)?.verify(total)?,
            "trie" => super::trie::Trie::open(&path, root)?.verify(total)?,
            "names" => super::names::Names::open(&path, root)?.verify(total)?,
            "intervals" => {
                let shard = super::intervals::Intervals::open(&path, root)?;
                shard.verify(total)?;
                if let Some((first, last)) = shard.span {
                    super::intervals::follows(previous_range, first)?;
                    previous_range = Some(last);
                }
            }
            _ => {}
        }
    }
    verify_forward(root, &manifest, total, metadata.countries.len())?;
    Ok(manifest)
}
fn verify_forward(
    root: &super::reader::Reader<'_>,
    manifest: &Manifest,
    total: usize,
    countries: usize,
) -> Result<()> {
    if manifest.forward_columns.is_some() {
        let count = manifest
            .core_catalogue
            .as_ref()
            .map_or(total, |p| p.place_count as usize);
        super::compact::Compact::open(root, manifest)?.verify(count)?;
    }
    if manifest.plate_columns.is_some() {
        let evidence = super::plate_columns::PlateColumns::open(root, manifest)?;
        let tables = evidence.decode(manifest)?;
        evidence.verify(&tables)?;
        crate::plates_index::PlateIndex::new(tables, evidence, countries)?;
    }
    Ok(())
}

//! Import the core ordinal namespace into bounded SQLite staging, never into a forward pack.
use crate::{Error, Result, error::ensure};
use rusqlite::{Connection, OptionalExtension};
use std::{fs, path::Path};
use thereabouts_core::format::{
    catalogue,
    container::Container,
    manifest::{self, CoreCatalogue},
};

pub(crate) fn pin(path: &Path, version: &str) -> Result<CoreCatalogue> {
    let manifest = manifest::read(path)?;
    ensure(
        manifest.family == "core" && manifest.data_version == version,
        "Core pack dataset version must agree",
    )?;
    let mut count = 0_u32;
    for f in manifest.files.iter().filter(|f| f.kind == "catalogue") {
        let shard = Container::decode(
            fs::read(manifest::artifact_path(path, &f.path)?)?,
            2,
            &[80, 8, 1],
        )?;
        count = count
            .checked_add(
                u32::try_from(shard.section(0).len() / 80)
                    .map_err(|_| Error::Input("Core catalogue exceeds u32".into()))?,
            )
            .ok_or_else(|| Error::Input("Core catalogue overflow".into()))?;
    }
    Ok(CoreCatalogue {
        data_version: version.into(),
        sha256: manifest::catalogue_digest(&manifest)?,
        place_count: count,
    })
}
pub(crate) fn load(db: &Connection, path: &Path, version: &str) -> Result<CoreCatalogue> {
    let pin = pin(path, version)?;
    let manifest = manifest::read(path)?;
    manifest::verify(path, &manifest)?;
    db.execute_batch("CREATE TABLE core_ids(id TEXT PRIMARY KEY,reference INTEGER) WITHOUT ROWID")?;
    let mut insert = db.prepare("INSERT INTO core_ids VALUES(?,?)")?;
    let mut ordinal = 0_u32;
    for file in manifest.files.iter().filter(|f| f.kind == "catalogue") {
        // Only one bounded shard is decoded at a time, never a world catalogue.
        let bytes = fs::read(manifest::artifact_path(path, &file.path)?)?;
        for place in catalogue::decode(bytes)? {
            ordinal += 1;
            insert.execute(rusqlite::params![place.field(0), ordinal])?;
        }
    }
    Ok(pin)
}
pub(crate) fn geography(
    dict: &crate::dictionaries::Dictionaries<'_>,
    local: [u32; 3],
) -> Result<Vec<u64>> {
    let db = dict.db;
    let mut row = Vec::with_capacity(7);
    for reference in local {
        let core: Option<u64> = db
            .prepare_cached(
                "SELECT c.reference FROM ids i JOIN core_ids c USING(id) WHERE i.reference=?",
            )?
            .query_row([reference], |r| r.get(0))
            .optional()?;
        row.push(core.unwrap_or(0));
    }
    for (reference, field) in [
        (local[0], "country_code"),
        (local[0], "name"),
        (local[1], "code"),
        (local[1], "name"),
    ] {
        let value: Option<String> = db
            .prepare_cached(&format!(
                "SELECT p.{field} FROM ids i JOIN places p USING(id) WHERE i.reference=?"
            ))?
            .query_row([reference], |r| r.get(0))
            .optional()?
            .flatten();
        row.push(dict.string(value.as_deref(), false)?);
    }
    Ok(row)
}

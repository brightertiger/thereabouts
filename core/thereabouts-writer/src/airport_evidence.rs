//! Multiple published assertions share one airport's query record.
use crate::{
    Result,
    compact::{Rows, encode_record, record},
    dictionaries::Dictionaries,
};
use rusqlite::Connection;
use std::path::Path;
use thereabouts_core::format::manifest::Manifest;
pub(crate) fn emit(
    db: &Connection,
    stage: &Path,
    manifest: &mut Manifest,
    dict: &Dictionaries<'_>,
) -> Result<()> {
    let mut aliases = Rows::new(stage, "airport_assertions");
    let mut spans = Rows::new(stage, "airport_evidence");
    let mut query = db.prepare("SELECT o.*,a.id FROM observations o JOIN airport_rows a ON o.source=a.source AND o.source_id=a.source_id GROUP BY o.key,a.id,o.name,o.details ORDER BY o.key COLLATE BINARY,a.id,o.name COLLATE BINARY,o.details COLLATE BINARY")?;
    let mut current = None;
    let mut first = 0;
    for row in query.query_map([], |r| Ok((r.get::<_, u64>(12)?, record(r)?)))? {
        let (id, (key, record)) = row?;
        let identity = (key, id);
        if current.as_ref() != Some(&identity) {
            if current.is_some() {
                spans.push(
                    manifest,
                    spans.count as u128,
                    vec![first as u64, (aliases.count - first) as u64],
                )?;
            }
            current = Some(identity);
            first = aliases.count;
        }
        let (_, fields) = encode_record(dict, &record, "airports")?;
        let name = dict.string(record.text.get(2).and_then(Option::as_deref), true)?;
        let detail = *fields
            .get(5)
            .ok_or_else(|| crate::Error::Input("Missing staged details".into()))?;
        aliases.push(manifest, aliases.count as u128, vec![name, detail])?;
    }
    if current.is_some() {
        spans.push(
            manifest,
            spans.count as u128,
            vec![first as u64, (aliases.count - first) as u64],
        )?;
    }
    aliases.finish(manifest)?;
    spans.finish(manifest)?;
    Ok(())
}

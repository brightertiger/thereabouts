//! Only key-specific assertions differing from an airport's record need storage.
use crate::{
    Result,
    compact::{Rows, encode_record, record},
    dictionaries::Dictionaries,
    error::ensure,
};
use rusqlite::Connection;
use std::path::Path;
use thereabouts_core::format::manifest::Manifest;
// A name/details pair is 16 bytes, limiting one key group to 64 KiB.
const MAX_ASSERTIONS_PER_KEY: usize = 4096;
pub(crate) fn emit(
    db: &Connection,
    stage: &Path,
    manifest: &mut Manifest,
    dict: &Dictionaries<'_>,
) -> Result<()> {
    let mut aliases = Rows::new(stage, "airport_assertions");
    let mut spans = Rows::new(stage, "airport_evidence");
    let mut query = db.prepare("SELECT o.*,a.id,a.name,a.details FROM observations o JOIN airport_rows a ON o.source=a.source AND o.source_id=a.source_id GROUP BY o.key,a.id,o.name,o.details ORDER BY o.key COLLATE BINARY,a.id,o.name COLLATE BINARY,o.details COLLATE BINARY")?;
    let mut current = None;
    let mut base = [0, 0];
    let mut assertions = Vec::new();
    for row in query.query_map([], |r| {
        Ok((
            r.get::<_, u64>(12)?,
            [r.get::<_, u64>(13)?, r.get::<_, u64>(14)?],
            record(r)?,
        ))
    })? {
        let (id, published, (key, record)) = row?;
        let identity = (key, id);
        if current.as_ref() != Some(&identity) {
            if current.is_some() {
                flush(&mut aliases, &mut spans, manifest, base, &assertions)?;
            }
            current = Some(identity);
            base = published;
            assertions.clear();
        }
        let (_, fields) = encode_record(dict, &record, "airports")?;
        let name = dict.string(record.text.get(2).and_then(Option::as_deref), true)?;
        let detail = *fields
            .get(5)
            .ok_or_else(|| crate::Error::Input("Missing staged details".into()))?;
        // One airport/key assertion group is admitted independently of the world row count.
        ensure(
            assertions.len() < MAX_ASSERTIONS_PER_KEY,
            "Too many assertions for one airport key",
        )?;
        assertions.push([name, detail]);
    }
    if current.is_some() {
        flush(&mut aliases, &mut spans, manifest, base, &assertions)?;
    }
    aliases.finish(manifest)?;
    spans.finish(manifest)?;
    Ok(())
}
fn flush(
    aliases: &mut Rows<'_>,
    spans: &mut Rows<'_>,
    manifest: &mut Manifest,
    base: [u64; 2],
    assertions: &[[u64; 2]],
) -> Result<()> {
    let first = aliases.count;
    if assertions != [base] {
        for assertion in assertions {
            aliases.push(manifest, aliases.count as u128, assertion.to_vec())?;
        }
    }
    spans.push(
        manifest,
        spans.count as u128,
        vec![first as u64, (aliases.count - first) as u64],
    )
}

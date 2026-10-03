//! Sorted starts with implicit ends; explicit null rows preserve every coverage gap.
use crate::{
    Result,
    compact::{Rows, encode_record, record},
    dictionaries::Dictionaries,
};
use rusqlite::Connection;
use std::path::Path;
use thereabouts_core::format::{
    intervals::{self, Bounds},
    manifest::Manifest,
};
pub(crate) fn emit(
    db: &Connection,
    stage: &Path,
    manifest: &mut Manifest,
    dict: &Dictionaries<'_>,
) -> Result<usize> {
    let mut starts4 = Rows::new(stage, "starts4");
    let mut starts6 = Rows::new(stage, "starts6");
    let mut evidence4 = Rows::new(stage, "evidence4");
    let mut evidence6 = Rows::new(stage, "evidence6");
    let mut previous: Option<Bounds> = None;
    let mut count = 0;
    let mut query = db.prepare("SELECT * FROM observations ORDER BY key COLLATE BINARY")?;
    for row in query.query_map([], record)? {
        let (key, record) = row?;
        let bounds = intervals::from_key(&key)?;
        intervals::follows(previous, bounds)?;
        if let Some(p) = previous {
            let maximum = if p.version == 4 {
                u128::from(u32::MAX)
            } else {
                u128::MAX
            };
            if p.last < maximum && (p.version != bounds.version || p.last + 1 < bounds.first) {
                let (starts, evidence) = if p.version == 4 {
                    (&mut starts4, &mut evidence4)
                } else {
                    (&mut starts6, &mut evidence6)
                };
                push(manifest, starts, evidence, p.last + 1, 0, vec![0; 6])?;
            }
        }
        let (location, fields) = encode_record(dict, &record, "ip")?;
        let (starts, evidence) = if bounds.version == 4 {
            (&mut starts4, &mut evidence4)
        } else {
            (&mut starts6, &mut evidence6)
        };
        push(manifest, starts, evidence, bounds.first, location, fields)?;
        previous = Some(bounds);
        count += 1;
    }
    if let Some(p) = previous {
        let maximum = if p.version == 4 {
            u128::from(u32::MAX)
        } else {
            u128::MAX
        };
        if p.last < maximum {
            let (starts, evidence) = if p.version == 4 {
                (&mut starts4, &mut evidence4)
            } else {
                (&mut starts6, &mut evidence6)
            };
            push(manifest, starts, evidence, p.last + 1, 0, vec![0; 6])?;
        }
    }
    starts4.finish(manifest)?;
    starts6.finish(manifest)?;
    evidence4.finish(manifest)?;
    evidence6.finish(manifest)?;
    Ok(count)
}
fn push(
    manifest: &mut Manifest,
    starts: &mut Rows<'_>,
    evidence: &mut Rows<'_>,
    address: u128,
    location: u64,
    fields: Vec<u64>,
) -> Result<()> {
    starts.push(
        manifest,
        address,
        vec![
            u64::try_from(address >> 64)
                .map_err(|_| crate::Error::Input("Invalid high address word".into()))?,
            u64::try_from(address & u128::from(u64::MAX))
                .map_err(|_| crate::Error::Input("Invalid low address word".into()))?,
            location,
        ],
    )?;
    evidence.push(manifest, address, fields)
}

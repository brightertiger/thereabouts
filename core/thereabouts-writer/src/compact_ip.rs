//! Sorted starts with implicit ends; explicit null rows preserve every coverage gap.
use crate::{Result, compact::Rows};
use rusqlite::Connection;
use std::path::Path;
use thereabouts_core::format::{
    intervals::{self, Bounds},
    manifest::Manifest,
};
pub(crate) fn emit(db: &Connection, stage: &Path, manifest: &mut Manifest) -> Result<usize> {
    let mut starts4 = Rows::new(stage, "starts4");
    let mut starts6 = Rows::new(stage, "starts6");
    let mut evidence4 = Rows::new(stage, "evidence4");
    let mut evidence6 = Rows::new(stage, "evidence6");
    let mut previous: Option<Bounds> = None;
    let mut count = 0;
    let mut query = db.prepare("SELECT * FROM packed_observations ORDER BY key")?;
    for row in query.query_map([], |r| {
        Ok((r.get::<_, Vec<u8>>(0)?, crate::packed_staging::numeric(r)?))
    })? {
        let (key, (location, fields)) = row?;
        let bounds = bounds(&key)?;
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

fn bounds(key: &[u8]) -> Result<Bounds> {
    crate::error::ensure(key.len() == 33, "Invalid packed IP sort key")?;
    let first = key
        .get(1..17)
        .and_then(|b| b.try_into().ok())
        .ok_or_else(|| crate::Error::Input("Missing interval start".into()))?;
    let last = key
        .get(17..33)
        .and_then(|b| b.try_into().ok())
        .ok_or_else(|| crate::Error::Input("Missing interval end".into()))?;
    Ok(Bounds {
        version: *key
            .first()
            .ok_or_else(|| crate::Error::Input("Missing IP version".into()))?,
        first: u128::from_be_bytes(first),
        last: u128::from_be_bytes(last),
    })
}

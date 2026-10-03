//! Bound each output unit independently of the dataset size.
// serde_json read indexing returns Null for absent fields, including non-objects.
#![allow(clippy::indexing_slicing)]
use super::{
    add, catalogue, flags,
    source::{Dataset, required},
    timezones,
};
use crate::{
    Error, Result,
    error::ensure,
    format::{self, address, manifest::Manifest, metadata::Metadata, spatial::Label},
};
use h3o::{CellIndex, LatLng, Resolution};
use rusqlite::Connection;
use std::{collections::BTreeMap, path::Path};
pub fn cells(
    data: &Dataset,
    db: &Connection,
    stage: &Path,
    manifest: &mut Manifest,
    metadata: &mut Metadata,
) -> Result<()> {
    let mut tables = data.tables("cells");
    tables.sort_by_key(|t| t["block"].as_str());
    for (i, table) in tables.iter().enumerate() {
        let root = required(table, "block")?
            .parse::<CellIndex>()
            .map_err(|_| Error::Input("Invalid block H3 cell".into()))?;
        ensure(
            root.resolution() == Resolution::Three,
            "Cell table is not a resolution-three block",
        )?;
        let block = address::address(root).0;
        let mut rows = vec![];
        data.scan(table, |row| {
            ensure(rows.len() < 16807, "Too many stored rows in a block")?;
            let cell = row
                .required("h3")?
                .parse::<CellIndex>()
                .map_err(|_| Error::Input("Invalid dataset H3 cell".into()))?;
            ensure(
                cell.resolution() >= Resolution::Three
                    && cell.resolution() <= Resolution::Eight
                    && cell.parent(Resolution::Three) == Some(root)
                    && row.unsigned("h3_uint64")? == Some(u64::from(cell))
                    && row.unsigned("h3_resolution")?
                        == Some(u64::from(u8::from(cell.resolution()))),
                "Dataset H3 columns disagree",
            )?;
            let country = catalogue::reference(db, row.text("country_id")?)?;
            let subdivision = catalogue::reference(db, row.text("state_id")?)?;
            let city = catalogue::reference(db, row.text("city_id")?)?;
            rows.push((
                address::address(cell).1,
                Label([country, subdivision, city, flags(row)?, 0]),
            ));
            Ok(())
        })?;
        rows.sort_unstable();
        let rows = timezones::join(db, block, rows, &mut metadata.timezone_sets)?;
        let bytes = format::spatial::encode_blocks(&BTreeMap::from([(block, rows)]))?;
        add(
            stage,
            manifest,
            &format!("cells-{i:05}.bin"),
            "cells",
            &bytes,
        )?;
    }
    Ok(())
}
pub fn catalogue(db: &Connection, stage: &Path, manifest: &mut Manifest) -> Result<()> {
    let mut query = db.prepare_cached("SELECT id FROM ids ORDER BY reference")?;
    let mut places = vec![];
    let mut size = 0;
    let mut shard = 0;
    for id in query.query_map([], |r| r.get::<_, String>(0))? {
        let mut place = catalogue::record(db, &id?)?;
        if let Some(point) = place.point() {
            let cell = LatLng::new(point.lat, point.lon)
                .map_err(|_| Error::Input("Invalid point".into()))?
                .to_cell(Resolution::Eight);
            place.timezone = timezones::at_point(db, cell)?;
        }
        let added = 80
            + place
                .text
                .iter()
                .flatten()
                .map(|s| s.len() + 8)
                .sum::<usize>();
        if size + added > 4 * 1024 * 1024 && !places.is_empty() {
            add(
                stage,
                manifest,
                &format!("catalogue-{shard:05}.bin"),
                "catalogue",
                &format::catalogue::encode_places(&places)?,
            )?;
            places.clear();
            size = 0;
            shard += 1;
        }
        size += added;
        places.push(place);
    }
    if !places.is_empty() {
        add(
            stage,
            manifest,
            &format!("catalogue-{shard:05}.bin"),
            "catalogue",
            &format::catalogue::encode_places(&places)?,
        )?;
    }
    Ok(())
}

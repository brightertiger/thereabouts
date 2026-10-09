//! Bound each output unit independently of the dataset size.
// serde_json read indexing returns Null for absent fields, including non-objects.
#![allow(clippy::indexing_slicing)]
use super::{add, catalogue, flags, source::Dataset, timezones};
use crate::{
    Error, Result,
    error::ensure,
    format::{self, address, manifest::Manifest, metadata::Metadata, spatial::Label},
};
use h3o::{CellIndex, LatLng, Resolution};
use rusqlite::Connection;
use std::path::Path;
/// Many blocks per shard, in ascending block order, up to the byte target.
pub fn cells(
    data: &Dataset,
    db: &Connection,
    stage: &Path,
    manifest: &mut Manifest,
    metadata: &mut Metadata,
    target: usize,
) -> Result<()> {
    let mut shard = format::spatial::Blocks::default();
    let mut count = 0;
    for input in &crate::cell_layout::blocks(data)? {
        let root = input.cell;
        let block = address::address(root).0;
        let mut rows = vec![];
        // A covered block without stored rows still answers no_land.
        if input.scan {
            data.scan_block(input, |row| {
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
        }
        rows.sort_unstable();
        let rows = timezones::join(db, block, rows, &mut metadata.timezone_sets)?;
        if !shard.is_empty() && shard.len() + format::spatial::block_bytes(&rows) > target {
            emit_cells(stage, manifest, &mut count, &shard)?;
            shard = format::spatial::Blocks::default();
        }
        shard.push(block, &rows)?;
    }
    if !shard.is_empty() {
        emit_cells(stage, manifest, &mut count, &shard)?;
    }
    Ok(())
}
fn emit_cells(
    stage: &Path,
    manifest: &mut Manifest,
    count: &mut usize,
    shard: &format::spatial::Blocks,
) -> Result<()> {
    add(
        stage,
        manifest,
        &format!("cells-{count:05}.bin"),
        "cells",
        &shard.encode()?,
    )?;
    *count += 1;
    Ok(())
}
pub fn catalogue(
    db: &Connection,
    stage: &Path,
    manifest: &mut Manifest,
    target: usize,
) -> Result<()> {
    let mut query = db.prepare_cached("SELECT id FROM ids ORDER BY reference")?;
    let mut places = vec![];
    let mut size = 0;
    let mut shard = 0;
    for id in query.query_map([], |r| r.get::<_, String>(0))? {
        let mut place = catalogue::record(db, &id?)?;
        if manifest.family != "core" {
            // Only result projection fields belong in a forward catalogue.
            for field in [3, 8, 9, 10, 11] {
                place.text[field] = None;
            }
        }
        if let Some(point) = place.point() {
            let cell = LatLng::new(point.lat, point.lon)
                .map_err(|_| Error::Input("Invalid point".into()))?
                .to_cell(Resolution::Eight);
            place.timezone = timezones::at_point(db, cell, Some(place.field(6)))?;
        }
        let added = 80
            + place
                .text
                .iter()
                .flatten()
                .map(|s| s.len() + 8)
                .sum::<usize>();
        if size + added > target && !places.is_empty() {
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

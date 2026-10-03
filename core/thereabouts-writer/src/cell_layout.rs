//! Dataset cell routing is declared by the manifest, never inferred from filenames.
use crate::{
    Error, Result,
    error::ensure,
    source::{Dataset, required},
};
use h3o::{CellIndex, Resolution};
use serde_json::Value;
use std::collections::BTreeSet;

pub(crate) struct Block<'a> {
    pub table: &'a Value,
    pub cell: CellIndex,
    pub row_group: Option<usize>,
    pub rows: u64,
}
fn cell(row: &Value) -> Result<CellIndex> {
    let cell = required(row, "block")?
        .parse::<CellIndex>()
        .map_err(|_| Error::Input("Invalid block H3 cell".into()))?;
    ensure(
        cell.resolution() == Resolution::Three,
        "Cell table is not a resolution-three block",
    )?;
    Ok(cell)
}
fn rows(row: &Value) -> Result<u64> {
    row.get("rows")
        .and_then(Value::as_u64)
        .ok_or_else(|| Error::Input("Missing nonnegative cells row count".into()))
}
pub(crate) fn blocks(data: &Dataset) -> Result<Vec<Block<'_>>> {
    let mut result = Vec::new();
    let mut seen = BTreeSet::new();
    for table in data.tables("cells") {
        let start = result.len();
        if let Some(entries) = table.get("blocks") {
            ensure(
                table.get("block").is_none(),
                "Mixed legacy and grouped cell routing",
            )?;
            let entries = entries
                .as_array()
                .ok_or_else(|| Error::Input("Cells blocks must be an array".into()))?;
            ensure(
                !entries.is_empty() && entries.len() <= 49,
                "A cell group needs 1 to 49 blocks",
            )?;
            let mut previous = None;
            let mut parent = None;
            for (index, entry) in entries.iter().enumerate() {
                let cell = cell(entry)?;
                ensure(
                    previous.is_none_or(|last| last < cell),
                    "Grouped cells blocks must be sorted and unique",
                )?;
                let group = cell.parent(Resolution::One);
                ensure(
                    parent.is_none_or(|p| Some(p) == group),
                    "Cell blocks have different resolution-one parents",
                )?;
                parent = group;
                previous = Some(cell);
                ensure(
                    entry.get("row_group").and_then(Value::as_u64) == Some(index as u64),
                    "Cells row groups must follow block order from zero",
                )?;
                result.push(Block {
                    table,
                    cell,
                    row_group: Some(index),
                    rows: rows(entry)?,
                });
            }
        } else {
            result.push(Block {
                table,
                cell: cell(table)?,
                row_group: None,
                rows: rows(table)?,
            });
        }
        let entries = result
            .get(start..)
            .ok_or_else(|| Error::Input("Invalid block routing".into()))?;
        for entry in entries {
            ensure(entry.rows <= 16807, "Too many stored rows in a block")?;
            ensure(seen.insert(entry.cell), "Repeated dataset cell block")?;
        }
        ensure(
            entries.iter().map(|b| b.rows).sum::<u64>() == rows(table)?,
            "Grouped cells row counts disagree with file",
        )?;
    }
    result.sort_by_key(|entry| entry.cell);
    Ok(result)
}

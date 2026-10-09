//! Dataset cell routing is declared by the manifest, never inferred from filenames.
use crate::{
    Error, Result,
    error::ensure,
    source::{Dataset, required},
};
use h3o::{CellIndex, Resolution};
use serde_json::Value;
use std::{collections::BTreeSet, path::Path};

pub(crate) struct Block<'a> {
    pub table: &'a Value,
    pub cell: CellIndex,
    pub row_group: Option<usize>,
    pub rows: u64,
    /// False for a grouped file's covered empty block: nothing is read for it.
    pub scan: bool,
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
/// Covered blocks without stored rows; grouped files list them beside their row groups.
fn covered<'a>(
    table: &'a Value,
    empty: &[Value],
    parent: CellIndex,
    result: &mut Vec<Block<'a>>,
) -> Result<()> {
    let mut previous = None;
    for value in empty {
        let cell = value
            .as_str()
            .and_then(|text| text.parse::<CellIndex>().ok())
            .filter(|cell| cell.resolution() == Resolution::Three)
            .ok_or_else(|| Error::Input("Invalid empty block H3 cell".into()))?;
        ensure(
            previous.is_none_or(|last| last < cell),
            "Empty cells blocks must be sorted and unique",
        )?;
        ensure(
            Some(parent) == cell.parent(Resolution::One),
            "Cell block parent differs from group path",
        )?;
        previous = Some(cell);
        result.push(Block {
            table,
            cell,
            row_group: None,
            rows: 0,
            scan: false,
        });
    }
    Ok(())
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
            let empty = match table.get("empty_blocks") {
                None => &[][..],
                Some(value) => value
                    .as_array()
                    .ok_or_else(|| Error::Input("Cells empty_blocks must be an array".into()))?,
            };
            ensure(
                entries.len() + empty.len() <= 49,
                "A cell group permits at most 49 blocks",
            )?;
            let parent = Path::new(required(table, "path")?)
                .parent()
                .and_then(Path::file_name)
                .and_then(|name| name.to_str())
                .and_then(|name| name.strip_prefix("group="))
                .and_then(|name| name.parse::<CellIndex>().ok())
                .filter(|cell| cell.resolution() == Resolution::One)
                .ok_or_else(|| Error::Input("Cells path needs group=<resolution-one H3>".into()))?;
            if entries.is_empty() {
                // Even an empty file is checksummed and its zero row-group footer admitted.
                data.scan(table, |_| {
                    Err(Error::Input("Empty cells group has rows".into()))
                })?;
            }
            let mut previous = None;
            for (index, entry) in entries.iter().enumerate() {
                let cell = cell(entry)?;
                ensure(
                    previous.is_none_or(|last| last < cell),
                    "Grouped cells blocks must be sorted and unique",
                )?;
                let group = cell.parent(Resolution::One);
                ensure(
                    Some(parent) == group,
                    "Cell block parent differs from group path",
                )?;
                previous = Some(cell);
                ensure(
                    entry.get("row_group").and_then(Value::as_u64) == Some(index as u64),
                    "Cells row groups must follow block order from zero",
                )?;
                ensure(
                    rows(entry)? > 0,
                    "Grouped block entries must have positive rows",
                )?;
                result.push(Block {
                    table,
                    cell,
                    row_group: Some(index),
                    rows: rows(entry)?,
                    scan: true,
                });
            }
            covered(table, empty, parent, &mut result)?;
        } else {
            ensure(
                table.get("empty_blocks").is_none(),
                "Legacy cells files record empty blocks as zero-row files",
            )?;
            result.push(Block {
                table,
                cell: cell(table)?,
                row_group: None,
                rows: rows(table)?,
                scan: true,
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

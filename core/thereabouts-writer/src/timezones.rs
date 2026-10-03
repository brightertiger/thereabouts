//! Join all matching timezones; overlapping source zones retain their complete set.
use super::inserts::Inserts;
use super::source::Dataset;
use crate::{
    Error, Result,
    error::ensure,
    format::{address, spatial::Label},
};
use h3o::{CellIndex, Resolution};
use rusqlite::{Connection, params, types::Value};
use std::collections::{BTreeMap, BTreeSet};

pub fn load(db: &Connection, data: &Dataset) -> Result<()> {
    let mut coarse = Inserts::new(db, "INSERT OR IGNORE INTO coarse_zones", 2);
    let mut fine = Inserts::new(db, "INSERT OR IGNORE INTO zones", 3);
    for table in data.tables("timezone_cells") {
        data.scan(table, |row| {
            let cell = row
                .required("h3")?
                .parse::<CellIndex>()
                .map_err(|_| Error::Input("Invalid timezone H3 cell".into()))?;
            ensure(
                cell.resolution() <= Resolution::Eight,
                "Timezone resolution exceeds eight",
            )?;
            let zone = row.required("tzid")?;
            if cell.resolution() < Resolution::Three {
                coarse.push([
                    Value::Integer(
                        i64::try_from(u64::from(cell))
                            .map_err(|_| Error::Input("Invalid H3 integer".into()))?,
                    ),
                    Value::Text(zone.into()),
                ])?;
            } else {
                let (block, key) = address::address(cell);
                fine.push([
                    Value::Integer(i64::from(block)),
                    Value::Integer(i64::from(key)),
                    Value::Text(zone.into()),
                ])?;
            }
            Ok(())
        })?;
    }
    let mut countries = Inserts::new(db, "INSERT OR IGNORE INTO zone_countries", 2);
    for table in data.tables("zone_tables") {
        data.scan(table, |row| {
            for country in row
                .text("country_codes")?
                .unwrap_or("")
                .split(',')
                .map(str::trim)
                .filter(|s| !s.is_empty())
            {
                countries.push([
                    Value::Text(row.required("tzid")?.into()),
                    Value::Text(country.into()),
                ])?;
            }
            Ok(())
        })?;
    }
    countries.flush()?;
    coarse.flush()?;
    fine.flush()?;
    Ok(())
}
pub fn block_zones(db: &Connection, block: u32) -> Result<BTreeMap<u64, BTreeSet<String>>> {
    let root = address::cell_at(block, 0)?;
    let mut zones = BTreeMap::<u64, BTreeSet<String>>::new();
    // Charge expanded labels conservatively, including tree and String overhead.
    let mut charged_bytes = 0;
    let mut add = |cell: CellIndex, zone: String| -> Result<()> {
        for child in cell.children(Resolution::Eight) {
            let names = zones.entry(u64::from(child)).or_default();
            if names.insert(zone.clone()) {
                charged_bytes += zone.len() + 128;
                ensure(
                    charged_bytes <= super::MEMORY_BUDGET_BYTES / 8,
                    "Expanded timezone block exceeds admission budget",
                )?;
            }
        }
        Ok(())
    };
    for resolution in [Resolution::Zero, Resolution::One, Resolution::Two] {
        if let Some(parent) = root.parent(resolution) {
            let mut query =
                db.prepare_cached("SELECT zone FROM coarse_zones WHERE cell=? ORDER BY zone")?;
            for z in query.query_map([u64::from(parent)], |r| r.get::<_, String>(0))? {
                add(root, z?)?;
            }
        }
    }
    let mut query =
        db.prepare_cached("SELECT key,zone FROM zones WHERE block=? ORDER BY key,zone")?;
    for row in query.query_map([block], |r| {
        Ok((r.get::<_, u16>(0)?, r.get::<_, String>(1)?))
    })? {
        let (key, zone) = row?;
        add(address::cell_at(block, key)?, zone)?;
    }
    Ok(zones)
}
pub fn join(
    db: &Connection,
    block: u32,
    rows: Vec<(u16, Label)>,
    sets: &mut Vec<Vec<String>>,
) -> Result<Vec<(u16, Label)>> {
    let zones = block_zones(db, block)?;
    if zones.is_empty() {
        return Ok(rows);
    }
    let mut registry: BTreeMap<_, _> = sets
        .iter()
        .cloned()
        .enumerate()
        .map(|(i, v)| (v, i))
        .collect();
    // Carry the source key through compaction: equal labels from distinct stored
    // cells must not create an ancestor that the dataset never published.
    let mut cells = BTreeMap::new();
    for (key, label) in rows {
        for child in address::cell_at(block, key)?.children(Resolution::Eight) {
            let names: Vec<_> = zones
                .get(&u64::from(child))
                .map_or_else(Vec::new, |v| v.iter().cloned().collect());
            let n = *registry.entry(names.clone()).or_insert_with(|| {
                let i = sets.len();
                sets.push(names);
                i
            });
            let mut label = label;
            label.0[4] =
                u32::try_from(n).map_err(|_| Error::Input("Too many timezone sets".into()))?;
            ensure(
                cells.insert(child, (label, key)).is_none(),
                "Overlapping dataset cells",
            )?;
        }
    }
    for r in (4..=8).rev() {
        let resolution =
            Resolution::try_from(r).map_err(|_| Error::Input("Invalid resolution".into()))?;
        let parent_res =
            Resolution::try_from(r - 1).map_err(|_| Error::Input("Invalid resolution".into()))?;
        let parents: BTreeSet<_> = cells
            .keys()
            .filter(|c| c.resolution() == resolution)
            .filter_map(|c| c.parent(parent_res))
            .collect();
        for parent in parents {
            let children: Vec<_> = parent.children(resolution).collect();
            let label = children.first().and_then(|child| cells.get(child)).copied();
            if let Some(label) = label
                && children.iter().all(|c| cells.get(c) == Some(&label))
            {
                for child in children {
                    cells.remove(&child);
                }
                cells.insert(parent, label);
            }
        }
    }
    let mut rows: Vec<_> = cells
        .into_iter()
        .map(|(c, (label, _origin))| (address::address(c).1, label))
        .collect();
    rows.sort_unstable();
    Ok(rows)
}

/// Catalogue anchors need only their matching ancestors, not expanded blocks.
pub fn at_point(db: &Connection, cell: CellIndex, country: Option<&str>) -> Result<Option<String>> {
    let mut names = BTreeSet::new();
    let (block, _) = address::address(cell);
    for r in 0..=8 {
        let resolution =
            Resolution::try_from(r).map_err(|_| Error::Input("Invalid resolution".into()))?;
        if let Some(parent) = cell.parent(resolution) {
            if r < 3 {
                let mut query = db.prepare_cached("SELECT zone FROM coarse_zones WHERE cell=?")?;
                for zone in query.query_map([u64::from(parent)], |row| row.get::<_, String>(0))? {
                    names.insert(zone?);
                }
            } else {
                let mut query =
                    db.prepare_cached("SELECT zone FROM zones WHERE block=? AND key=?")?;
                for zone in query.query_map(params![block, address::address(parent).1], |row| {
                    row.get::<_, String>(0)
                })? {
                    names.insert(zone?);
                }
            }
        }
    }
    if let Some(country) = country {
        let mut narrowed = BTreeSet::new();
        for name in &names {
            let present: bool = db
                .prepare_cached(
                    "SELECT EXISTS(SELECT 1 FROM zone_countries WHERE zone=? AND country=?)",
                )?
                .query_row(params![name, country], |row| row.get(0))?;
            if present {
                narrowed.insert(name.clone());
            }
        }
        if !narrowed.is_empty() {
            names = narrowed;
        }
    }
    Ok(if names.len() == 1 {
        names.into_iter().next()
    } else {
        None
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::catalogue;
    #[test]
    fn equal_labels_from_distinct_source_cells_never_merge_above_their_resolution() {
        let db = Connection::open_in_memory().unwrap();
        catalogue::initialize(&db).unwrap();
        let root = h3o::LatLng::new(52.0, 4.0)
            .unwrap()
            .to_cell(Resolution::Three);
        let block = address::address(root).0;
        db.execute(
            "INSERT INTO zones VALUES (?,?,?)",
            params![block, 0, "Area/One"],
        )
        .unwrap();
        let rows: Vec<_> = root
            .children(Resolution::Four)
            .map(|cell| (address::address(cell).1, Label([0; 5])))
            .collect();
        let original: Vec<_> = rows.iter().map(|(key, _)| *key).collect();
        let output = join(&db, block, rows, &mut vec![vec![]]).unwrap();
        assert_eq!(
            output.iter().map(|(key, _)| *key).collect::<Vec<_>>(),
            original
        );
    }
    #[test]
    fn overlapping_zones_split_labels_and_never_choose_one() {
        let db = Connection::open_in_memory().unwrap();
        catalogue::initialize(&db).unwrap();
        let root = h3o::LatLng::new(52.0, 4.0)
            .unwrap()
            .to_cell(Resolution::Three);
        let block = address::address(root).0;
        let fine = root.center_child(Resolution::Eight).unwrap();
        let key = address::address(fine).1;
        for zone in ["Europe/Amsterdam", "Europe/Berlin"] {
            db.execute(
                "INSERT INTO zones VALUES (?,?,?)",
                params![block, key, zone],
            )
            .unwrap();
        }
        let mut sets = vec![vec![]];
        let rows = join(&db, block, vec![(0, Label([0; 5]))], &mut sets).unwrap();
        assert_eq!(sets[1], vec!["Europe/Amsterdam", "Europe/Berlin"]);
        assert_eq!(rows.iter().find(|(k, _)| *k == key).unwrap().1.0[4], 1);
        assert_eq!(at_point(&db, fine, None).unwrap(), None);
        db.execute(
            "INSERT INTO zone_countries VALUES ('Europe/Amsterdam','NL')",
            [],
        )
        .unwrap();
        assert_eq!(
            at_point(&db, fine, Some("NL")).unwrap().as_deref(),
            Some("Europe/Amsterdam")
        );
        assert_eq!(at_point(&db, fine, Some("ZZ")).unwrap(), None);
        db.execute("DELETE FROM zones WHERE zone='Europe/Berlin'", [])
            .unwrap();
        assert_eq!(
            at_point(&db, fine, Some("ZZ")).unwrap().as_deref(),
            Some("Europe/Amsterdam")
        );
        assert!(rows.len() > 1);
    }
}

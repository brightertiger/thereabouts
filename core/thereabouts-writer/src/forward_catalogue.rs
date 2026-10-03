//! Forward exports stage only the referenced place closure, without catalogue provenance.
use crate::{Result, catalogue, error::ensure, inserts::Inserts, source::Dataset};
use rusqlite::{Connection, types::Value};
use std::collections::{HashMap, HashSet};
/// At most 128 MiB of estimated owned ID storage, leaving the Arrow/SQLite budget intact.
const SELECTION_BYTES: usize = 128 * 1024 * 1024;
pub(crate) struct Selection {
    pub(crate) needed: HashSet<String>,
    pub(crate) loaded: HashMap<String, usize>,
    pub(crate) generation: usize,
    bytes: usize,
}
impl Selection {
    pub(crate) fn include(&mut self, id: &str) -> Result<()> {
        if self.needed.insert(id.into()) {
            // Two sets, two String headers and allocator/hash-table overhead.
            self.bytes += 2 * id.len() + 128;
            ensure(
                self.bytes <= SELECTION_BYTES,
                "Place closure exceeds selection budget",
            )?;
        }
        Ok(())
    }
}
pub(crate) fn load(db: &Connection, data: &Dataset, kind: &str) -> Result<()> {
    catalogue::seed(db, data, kind)?;
    let mut selected = Selection {
        needed: HashSet::new(),
        loaded: HashMap::new(),
        generation: 0,
        bytes: 0,
    };
    let mut query = db.prepare("SELECT id FROM needed")?;
    for id in query.query_map([], |r| r.get::<_, String>(0))? {
        selected.include(&id?)?;
    }
    while selected.loaded.len() < selected.needed.len() {
        let before = selected.loaded.len();
        selected.generation += 1;
        catalogue::load_places(db, data, Some(&mut selected))?;
        ensure(
            selected.loaded.len() > before,
            "Dangling dataset place reference",
        )?;
    }
    let mut needed = Inserts::new(db, "INSERT OR IGNORE INTO needed", 1);
    for id in &selected.needed {
        needed.push([Value::Text(id.clone())])?;
    }
    needed.flush()?;
    catalogue::load_cities(db, data)?;
    let mut mappings = Inserts::new(db, "INSERT INTO mappings", 2);
    for table in data.tables("place_to_city") {
        data.scan(table, |row| {
            let id = row.required("place_id")?;
            if selected.needed.contains(id) {
                mappings.push([Value::Text(id.into()), row.sql_text("city_id")?])?;
            }
            Ok(())
        })?;
    }
    mappings.flush()?;
    db.execute(
        "INSERT INTO ids(id) SELECT id FROM needed ORDER BY id COLLATE BINARY",
        [],
    )?;
    Ok(())
}

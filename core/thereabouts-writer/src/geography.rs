//! Resolve published canonical and administrative ancestors without spatial inference.
use crate::{Result, catalogue, error::ensure};
use rusqlite::Connection;
pub(crate) fn geography(db: &Connection, country: u32, id: &str) -> Result<[u32; 3]> {
    let place = catalogue::record(db, id)?;
    let reference = catalogue::reference(db, Some(id))?;
    let city = if place.refs[3] != 0 {
        place.refs[3]
    } else if place.field(4) == "city" {
        reference
    } else {
        0
    };
    let mut state = 0;
    let mut parent = Some(id.to_owned());
    let mut seen = std::collections::BTreeSet::new();
    while let Some(id) = parent {
        ensure(seen.insert(id.clone()), "Cyclic place ancestry")?;
        let place = catalogue::record(db, &id)?;
        if place.field(4) == "state" {
            state = catalogue::reference(db, Some(&id))?;
            break;
        }
        parent = db.query_row("SELECT parent_id FROM places WHERE id=?", [id], |r| {
            r.get(0)
        })?;
    }
    Ok([country, state, city])
}

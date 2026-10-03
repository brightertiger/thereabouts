//! Trade-location source fields are retained alongside published canonical associations.
use crate::{Result, error::ensure, forward, inserts::Inserts, source::Dataset};
use rusqlite::Connection;
pub(crate) fn load(data: &Dataset, db: &Connection) -> Result<()> {
    forward::initialize(db)?;
    let mut inserts = Inserts::new(db, "INSERT INTO observations", 12);
    for table in data.tables("trade_locations") {
        data.scan(table, |row| {
            let code = row.required("locode")?;
            ensure(thereabouts_core::locode::valid(code), "Invalid LOCODE")?;
            ensure(
                code == format!(
                    "{}{}",
                    row.required("country_code")?,
                    row.required("location")?
                ),
                "LOCODE components disagree",
            )?;
            let mut details = serde_json::Map::new();
            for field in [
                "name_ascii",
                "subdivision_code",
                "function",
                "status",
                "iata_code",
                "date",
                "change",
                "remarks",
                "coordinates_raw",
            ] {
                if let Some(value) = row.text(field)? {
                    details.insert(field.into(), serde_json::Value::String(value.into()));
                }
            }
            let record = forward::association(
                db,
                row,
                "name",
                code,
                Some("unlocode"),
                Some(serde_json::to_string(&details)?),
            )?;
            forward::insert(&mut inserts, code.into(), record)
        })?;
    }
    inserts.flush()
}

//! Index every published airport scheme without inventing codes from identifiers.
use crate::{Result, error::ensure, forward, inserts::Inserts, source::Dataset};
use rusqlite::Connection;
use thereabouts_core::{airports::SCHEMES, forward::normalize_code};
pub(crate) const NORMALIZATION: [&str; 2] = ["strip_ascii", "upper_ascii"];
pub(crate) fn load(data: &Dataset, db: &Connection) -> Result<()> {
    forward::initialize(db)?;
    let rules: Vec<_> = NORMALIZATION.iter().map(|s| (*s).to_owned()).collect();
    let mut inserts = Inserts::new(db, "INSERT INTO observations", 12);
    for table in data.tables("airports") {
        data.scan(table, |row| {
            let country = row.required("country_code")?;
            ensure(country.len() == 2 && country.bytes().all(|b| b.is_ascii_uppercase()), "Invalid airport country")?;
            let details = serde_json::json!({"type":row.text("type")?, "municipality":row.text("municipality")?, "region_code":row.text("region_code")?}).to_string();
            for (scheme, field) in SCHEMES.into_iter().zip(["iata_code", "icao_code", "gps_code", "local_code", "ident"]) {
                let Some(raw) = row.text(field)? else { continue; };
                let Some(code) = normalize_code(raw, &rules) else { continue; };
                let record = forward::association(db, row, "name", &code, Some(scheme), Some(details.clone()))?;
                if scheme != "local" {
                    forward::insert(&mut inserts, format!("{scheme}\0\0{code}"), record.clone())?;
                }
                forward::insert(&mut inserts, format!("{scheme}\0{country}\0{code}"), record)?;
            }
            Ok(())
        })?;
    }
    inserts.flush()
}

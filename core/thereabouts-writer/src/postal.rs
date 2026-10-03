//! Export country-scoped postal codes without losing source point or administrative names.
use crate::{Error, Result, error::ensure, forward, packed_staging::Packed, source::Dataset};
use rusqlite::Connection;
use thereabouts_core::forward::normalize_code;
pub(crate) const NORMALIZATION: [&str; 3] = ["strip_ascii", "upper_ascii", "remove_ascii_spaces"];
pub(crate) fn load(data: &Dataset, db: &Connection) -> Result<()> {
    let rules: Vec<_> = NORMALIZATION.iter().map(|s| (*s).to_owned()).collect();
    let mut countries = std::collections::BTreeMap::<String, bool>::new();
    let mut inserts = Packed::new(db, "postal")?;
    for table in data.tables("postal_codes") {
        data.scan(table, |row| {
            let country = row.required("country_code")?;
            ensure(
                country.len() == 2 && country.bytes().all(|b| b.is_ascii_uppercase()),
                "Invalid postal country",
            )?;
            let code = normalize_code(row.required("postal_code")?, &rules)
                .ok_or_else(|| Error::Input("Invalid postal code".into()))?;
            let mut details = serde_json::Map::new();
            for field in [
                "admin1_name",
                "admin1_code",
                "admin2_name",
                "admin2_code",
                "admin3_name",
                "admin3_code",
                "accuracy",
                "variant",
            ] {
                if let Some(value) = row.text(field)? {
                    details.insert(field.into(), serde_json::Value::String(value.into()));
                }
            }
            let record = forward::association(
                db,
                row,
                "place_name",
                &code,
                None,
                Some(serde_json::to_string(&details)?),
            )?;
            let unlinked = record.places.first() == Some(&0);
            countries
                .entry(country.to_owned())
                .and_modify(|needed| *needed |= unlinked)
                .or_insert(unlinked);
            inserts.push(
                rusqlite::types::Value::Text(format!("{country}\0{code}")),
                &record,
            )
        })?;
    }
    inserts.finish()?;
    db.execute_batch(
        "CREATE TABLE postal_countries(country TEXT PRIMARY KEY,needs_metadata INTEGER)",
    )?;
    for (country, needed) in countries {
        db.execute(
            "INSERT INTO postal_countries VALUES(?,?)",
            rusqlite::params![country, needed],
        )?;
    }
    Ok(())
}

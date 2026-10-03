//! A disk index keeps global place closure and sorting out of process memory.
use super::inserts::Inserts;
use super::source::{Dataset, population, required};
use crate::{
    Error, Result,
    error::ensure,
    format::catalogue::{Place, REF_FIELDS, TEXT_FIELDS},
};
use rusqlite::{Connection, OptionalExtension, types::Value as SqlValue};
use serde_json::{Value, json};

pub fn initialize(db: &Connection) -> Result<()> {
    db.execute_batch("PRAGMA cache_size=-16384; PRAGMA temp_store=FILE;
        CREATE TABLE places(id TEXT PRIMARY KEY,payload TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE cities(id TEXT PRIMARY KEY,payload TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE mappings(id TEXT PRIMARY KEY,city TEXT);
        CREATE TABLE needed(id TEXT PRIMARY KEY) WITHOUT ROWID;
        CREATE TABLE ids(reference INTEGER PRIMARY KEY,id TEXT UNIQUE);
        CREATE TABLE zones(block INTEGER,key INTEGER,zone TEXT,PRIMARY KEY(block,key,zone)) WITHOUT ROWID;
        CREATE TABLE coarse_zones(cell INTEGER,zone TEXT,PRIMARY KEY(cell,zone)) WITHOUT ROWID;")?;
    Ok(())
}
#[allow(clippy::indexing_slicing)] // Arrow rows are objects; serde_json reads return Null.
pub fn load(db: &Connection, data: &Dataset) -> Result<()> {
    for kind in ["places", "canonical_cities", "place_to_city"] {
        let prefix = match kind {
            "places" => "INSERT INTO places",
            "canonical_cities" => "INSERT INTO cities",
            _ => "INSERT INTO mappings",
        };
        let mut inserts = Inserts::new(db, prefix, 2);
        for table in data.tables(kind) {
            data.scan(table,|mut row| {
                ensure(row.is_object(), "Dataset row must be an object")?;
                if kind != "place_to_city" { population(&row)?; }
                match kind {
                    "places" => {
                        let evidence=json!({"source_ids":row["source_ids"].as_str().and_then(|s|serde_json::from_str::<Value>(s).ok()),"golden_table":table["path"],"name_provenance":row["name_provenance"].as_str().and_then(|s|serde_json::from_str::<Value>(s).ok())});
                        row["evidence"]=Value::String(serde_json::to_string(&evidence)?);
                        row["country_id"]=Value::String(format!("country:{}",required(&row,"country_code")?));
                        if let Some(object)=row.as_object_mut() {object.retain(|k,_| TEXT_FIELDS.contains(&k.as_str()) || REF_FIELDS.contains(&k.as_str()) || k=="population");}
                        inserts.push([SqlValue::Text(required(&row,"place_id")?.into()),SqlValue::Text(row.to_string())])?;
                    },
                    "canonical_cities" => {inserts.push([SqlValue::Text(required(&row,"city_id")?.into()),SqlValue::Text(row.to_string())])?;},
                    _ => {inserts.push([SqlValue::Text(required(&row,"place_id")?.into()),row["city_id"].as_str().map_or(SqlValue::Null,|v|SqlValue::Text(v.into()))])?;},
                } Ok(())
            })?;
        }
        inserts.flush()?;
    }
    let mut needed = Inserts::new(db, "INSERT OR IGNORE INTO needed", 1);
    for table in data.tables("cells") {
        data.scan(table, |row| {
            for field in ["country_id", "state_id", "city_id"] {
                if let Some(id) = row[field].as_str() {
                    needed.push([SqlValue::Text(id.into())])?;
                }
            }
            Ok(())
        })?;
    }
    needed.flush()?;
    loop {
        let changed = db.total_changes();
        for field in REF_FIELDS {
            db.prepare_cached(&format!("INSERT OR IGNORE INTO needed SELECT json_extract(p.payload,'$.{field}') FROM places p JOIN needed n USING(id) WHERE json_extract(p.payload,'$.{field}') IS NOT NULL"))?.execute([])?;
        }
        if changed == db.total_changes() {
            break;
        }
    }
    let missing: Option<String> = db
        .query_row(
            "SELECT id FROM needed LEFT JOIN places USING(id) WHERE payload IS NULL LIMIT 1",
            [],
            |r| r.get(0),
        )
        .optional()?;
    ensure(missing.is_none(), "Dangling dataset place reference")?;
    db.prepare_cached("INSERT INTO ids(id) SELECT id FROM needed ORDER BY id COLLATE BINARY")?
        .execute([])?;
    Ok(())
}
pub fn reference(db: &Connection, id: Option<&str>) -> Result<u32> {
    match id {
        None => Ok(0),
        Some(id) => Ok(db
            .prepare_cached("SELECT reference FROM ids WHERE id=?")?
            .query_row([id], |r| r.get(0))?),
    }
}
#[allow(clippy::indexing_slicing)] // Stored rows are objects and field arrays have fixed schema lengths.
pub fn record(db: &Connection, id: &str) -> Result<Place> {
    let payload: String = db
        .prepare_cached("SELECT payload FROM places WHERE id=?")?
        .query_row([id], |r| r.get(0))?;
    let mut row: Value = serde_json::from_str(&payload)?;
    ensure(row.is_object(), "Catalogue payload must be an object")?;
    if let Some(canonical) = db
        .prepare_cached("SELECT payload FROM cities WHERE id=?")?
        .query_row([id], |r| r.get::<_, String>(0))
        .optional()?
    {
        let canonical: Value = serde_json::from_str(&canonical)?;
        for field in ["name", "name_en", "population", "latitude", "longitude"] {
            row[field] = canonical[field].clone();
        }
        row["settlement_kind"] = canonical["kind"].clone();
    }
    // A supplied mapping must agree with the published normalized identity.
    if let Some(mapped) = db
        .prepare_cached("SELECT city FROM mappings WHERE id=?")?
        .query_row([id], |r| r.get::<_, Option<String>>(0))
        .optional()?
    {
        ensure(
            mapped.as_deref() == row["normalized_city_id"].as_str(),
            "Place mapping disagrees with catalogue",
        )?;
    }
    let mut refs = [0; 4];
    for (i, field) in REF_FIELDS.iter().enumerate() {
        refs[i] = reference(db, row[field].as_str())?;
    }
    let point = match (row["latitude"].as_f64(), row["longitude"].as_f64()) {
        (Some(lat), Some(lon))
            if lat.is_finite() && lon.is_finite() && lat.abs() <= 90.0 && lon.abs() <= 180.0 =>
        {
            (microdegrees(lat), microdegrees(lon))
        }
        (None, None) => (i32::MIN, i32::MIN),
        _ => return Err(Error::Input("Invalid catalogue coordinates".into())),
    };
    Ok(Place {
        text: std::array::from_fn(|i| row[TEXT_FIELDS[i]].as_str().map(str::to_owned)),
        refs,
        latitude: point.0,
        longitude: point.1,
        population: population(&row)?,
        timezone: None,
    })
}
#[allow(clippy::cast_possible_truncation)] // Geographic bounds are checked by the caller.
fn microdegrees(value: f64) -> i32 {
    (value * 1e6).round() as i32
}

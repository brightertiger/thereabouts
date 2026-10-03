//! Typed SQLite columns keep global place closure and sorting out of process memory.
use super::{
    inserts::Inserts,
    source::{Dataset, required},
};
use crate::{
    Error, Result,
    error::ensure,
    format::catalogue::{Place, REF_FIELDS, TEXT_FIELDS},
};
use rusqlite::{Connection, OptionalExtension, types::Value as SqlValue};
use serde_json::{Value, json};
pub fn initialize(db: &Connection) -> Result<()> {
    db.execute_batch("PRAGMA cache_size=-16384; PRAGMA temp_store=FILE;
        CREATE TABLE places(id TEXT PRIMARY KEY,name TEXT,name_en TEXT,local_name TEXT,
          role TEXT,settlement_kind TEXT,country_code TEXT,code TEXT,code_status TEXT,
          parent_method TEXT,normalization_method TEXT,evidence TEXT,country_id TEXT,
          parent_id TEXT,sovereign_id TEXT,normalized_city_id TEXT,population INTEGER) WITHOUT ROWID;
        CREATE TABLE cities(id TEXT PRIMARY KEY,name TEXT,name_en TEXT,kind TEXT,
          population INTEGER,latitude REAL,longitude REAL) WITHOUT ROWID;
        CREATE TABLE mappings(id TEXT PRIMARY KEY,city TEXT);
        CREATE TABLE needed(id TEXT PRIMARY KEY) WITHOUT ROWID;
        CREATE TABLE ids(reference INTEGER PRIMARY KEY,id TEXT UNIQUE);
        CREATE TABLE zones(block INTEGER,key INTEGER,zone TEXT,PRIMARY KEY(block,key,zone)) WITHOUT ROWID;
        CREATE TABLE coarse_zones(cell INTEGER,zone TEXT,PRIMARY KEY(cell,zone)) WITHOUT ROWID;")?;
    Ok(())
}
pub fn load(db: &Connection, data: &Dataset, kind: &str) -> Result<()> {
    load_places(db, data)?;
    load_cities(db, data)?;
    let mut mappings = Inserts::new(db, "INSERT INTO mappings", 2);
    for table in data.tables("place_to_city") {
        data.scan(table, |row| {
            mappings.push([
                SqlValue::Text(row.required("place_id")?.into()),
                row.sql_text("city_id")?,
            ])
        })?;
    }
    mappings.flush()?;
    let mut needed = Inserts::new(db, "INSERT OR IGNORE INTO needed", 1);
    let kinds = if kind == "phone_prefixes" {
        vec![kind, "phone_metadata"]
    } else {
        vec![kind]
    };
    for table in kinds.iter().flat_map(|kind| data.tables(kind)) {
        data.scan(table, |row| {
            for field in ["country_id", "state_id", "city_id", "place_id"] {
                if let Some(id) = row.text(field)? {
                    needed.push([SqlValue::Text(id.into())])?;
                }
            }
            if kind == "phone_prefixes" {
                for id in row.texts("place_ids")? {
                    needed.push([SqlValue::Text(id)])?;
                }
                let mut countries = row.texts("country_codes")?;
                if let Some(code) = row.text("territory")? {
                    countries.push(code.into());
                }
                for code in countries {
                    if code != "001" {
                        needed.push([SqlValue::Text(format!("country:{code}"))])?;
                    }
                }
            }
            Ok(())
        })?;
    }
    needed.flush()?;
    loop {
        let changed = db.total_changes();
        for field in REF_FIELDS {
            db.prepare_cached(&format!("INSERT OR IGNORE INTO needed SELECT p.{field} FROM places p JOIN needed n USING(id) WHERE p.{field} IS NOT NULL"))?.execute([])?;
        }
        if changed == db.total_changes() {
            break;
        }
    }
    let missing: Option<String> = db
        .query_row(
            "SELECT n.id FROM needed n LEFT JOIN places p USING(id) WHERE p.id IS NULL LIMIT 1",
            [],
            |r| r.get(0),
        )
        .optional()?;
    ensure(missing.is_none(), "Dangling dataset place reference")?;
    db.prepare_cached("INSERT INTO ids(id) SELECT id FROM needed ORDER BY id COLLATE BINARY")?
        .execute([])?;
    Ok(())
}
fn load_places(db: &Connection, data: &Dataset) -> Result<()> {
    let mut inserts = Inserts::new(db, "INSERT INTO places", 17);
    for table in data.tables("places") {
        let table_path = required(table, "path")?;
        data.scan(table, |row| {
            row.required("place_id")?;
            let population = row.population()?;
            let mut values = Vec::with_capacity(17);
            for field in TEXT_FIELDS {
                values.push(if field == "evidence" {
                    // These are published JSON provenance fields, not a serialized dataset row.
                    let evidence = json!({"source_ids":row.text("source_ids")?.and_then(|s| serde_json::from_str::<Value>(s).ok()), "golden_table":table_path, "name_provenance":row.text("name_provenance")?.and_then(|s| serde_json::from_str::<Value>(s).ok())});
                    SqlValue::Text(serde_json::to_string(&evidence)?)
                } else { row.sql_text(field)? });
            }
            for field in REF_FIELDS {
                values.push(if field == "country_id" { SqlValue::Text(format!("country:{}", row.required("country_code")?)) } else { row.sql_text(field)? });
            }
            values.push(SqlValue::Integer(i64::from(population)));
            inserts.push(values)
        })?;
    }
    inserts.flush()
}
fn load_cities(db: &Connection, data: &Dataset) -> Result<()> {
    let mut inserts = Inserts::new(db, "INSERT INTO cities", 7);
    for table in data.tables("canonical_cities") {
        data.scan(table, |row| {
            inserts.push([
                SqlValue::Text(row.required("city_id")?.into()),
                row.sql_text("name")?,
                row.sql_text("name_en")?,
                row.sql_text("kind")?,
                SqlValue::Integer(i64::from(row.population()?)),
                row.number("latitude")?
                    .map_or(SqlValue::Null, SqlValue::Real),
                row.number("longitude")?
                    .map_or(SqlValue::Null, SqlValue::Real),
            ])
        })?;
    }
    inserts.flush()
}
pub fn reference(db: &Connection, id: Option<&str>) -> Result<u32> {
    match id {
        None => Ok(0),
        Some(id) => Ok(db
            .prepare_cached("SELECT reference FROM ids WHERE id=?")?
            .query_row([id], |r| r.get(0))?),
    }
}
pub fn record(db: &Connection, id: &str) -> Result<Place> {
    let (mut text, ids, mut population) = db
        .prepare_cached("SELECT * FROM places WHERE id=?")?
        .query_row([id], |row| {
            let mut text: [Option<String>; 12] = std::array::from_fn(|_| None);
            let mut ids: [Option<String>; 4] = std::array::from_fn(|_| None);
            for (i, value) in text.iter_mut().enumerate() {
                *value = row.get(i)?;
            }
            for (i, value) in ids.iter_mut().enumerate() {
                *value = row.get(12 + i)?;
            }
            Ok((text, ids, row.get::<_, u32>(16)?))
        })?;
    let mut point = (i32::MIN, i32::MIN);
    let canonical = db
        .prepare_cached(
            "SELECT name,name_en,kind,population,latitude,longitude FROM cities WHERE id=?",
        )?
        .query_row([id], |r| {
            Ok((
                r.get::<_, Option<String>>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<String>>(2)?,
                r.get::<_, u32>(3)?,
                r.get::<_, Option<f64>>(4)?,
                r.get::<_, Option<f64>>(5)?,
            ))
        })
        .optional()?;
    if let Some((name, name_en, kind, count, lat, lon)) = canonical {
        for (i, value) in [(1, name), (2, name_en), (5, kind)] {
            if let Some(field) = text.get_mut(i) {
                *field = value;
            }
        }
        population = count;
        point = match (lat, lon) {
            (Some(lat), Some(lon))
                if lat.is_finite()
                    && lon.is_finite()
                    && lat.abs() <= 90.0
                    && lon.abs() <= 180.0 =>
            {
                (microdegrees(lat), microdegrees(lon))
            }
            (None, None) => point,
            _ => return Err(Error::Input("Invalid catalogue coordinates".into())),
        };
    }
    if let Some(mapped) = db
        .prepare_cached("SELECT city FROM mappings WHERE id=?")?
        .query_row([id], |r| r.get::<_, Option<String>>(0))
        .optional()?
    {
        ensure(
            mapped == ids.get(3).cloned().flatten(),
            "Place mapping disagrees with catalogue",
        )?;
    }
    let mut refs = [0; 4];
    for (value, id) in refs.iter_mut().zip(ids.iter()) {
        *value = reference(db, id.as_deref())?;
    }
    Ok(Place {
        text,
        refs,
        latitude: point.0,
        longitude: point.1,
        population,
        timezone: None,
    })
}
#[allow(clippy::cast_possible_truncation)] // Geographic bounds are checked by the caller.
fn microdegrees(value: f64) -> i32 {
    (value * 1e6).round() as i32
}

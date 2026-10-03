//! Bounded typed staging and emission for forward source associations.
use crate::{
    Error, Result, add,
    arrow::Row,
    catalogue,
    error::ensure,
    format::{exact::encode_entries, manifest::Manifest, observation::Observation},
    inserts::Inserts,
};
use rusqlite::{Connection, OptionalExtension, types::Value};
use std::path::Path;
type Encoder = fn(&[(String, Observation)]) -> thereabouts_core::Result<Vec<u8>>;
pub(crate) fn initialize(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE observations(key TEXT,country INTEGER,state INTEGER,city INTEGER,latitude INTEGER,longitude INTEGER,source TEXT,source_id TEXT,name TEXT,code TEXT,scheme TEXT,details TEXT)")?;
    Ok(())
}
pub(crate) fn association(
    db: &Connection,
    row: Row<'_>,
    name: &str,
    code: &str,
    scheme: Option<&str>,
    details: Option<String>,
) -> Result<Observation> {
    let city = row.text("city_id")?;
    let canonical = if let Some(city) = city {
        db.prepare_cached("SELECT city FROM mappings WHERE id=?")?
            .query_row([city], |r| r.get::<_, Option<String>>(0))
            .optional()?
            .flatten()
    } else {
        None
    };
    let city = canonical.as_deref().or(city);
    let (latitude, longitude) = point(row.number("latitude")?, row.number("longitude")?)?;
    Ok(Observation {
        places: [
            catalogue::reference(db, row.text("country_id")?)?,
            catalogue::reference(db, row.text("state_id")?)?,
            catalogue::reference(db, city)?,
        ],
        latitude,
        longitude,
        text: [
            Some(row.required("source")?.into()),
            Some(row.required("source_id")?.into()),
            row.text(name)?.map(str::to_owned),
            Some(code.into()),
            scheme.map(str::to_owned),
            details,
        ],
    })
}
#[allow(clippy::cast_possible_truncation)] // Geographic bounds are admitted before microdegree conversion.
pub(crate) fn point(lat: Option<f64>, lon: Option<f64>) -> Result<(i32, i32)> {
    match (lat, lon) {
        (None, None) => Ok((i32::MIN, i32::MIN)),
        (Some(lat), Some(lon))
            if lat.is_finite() && lon.is_finite() && lat.abs() <= 90.0 && lon.abs() <= 180.0 =>
        {
            Ok(((lat * 1e6).round() as i32, (lon * 1e6).round() as i32))
        }
        _ => Err(Error::Input("Invalid source point".into())),
    }
}
pub(crate) fn insert(rows: &mut Inserts<'_>, key: String, record: Observation) -> Result<()> {
    let mut values = vec![Value::Text(key)];
    values.extend(
        record
            .places
            .into_iter()
            .map(|v| Value::Integer(i64::from(v))),
    );
    values.extend([
        Value::Integer(i64::from(record.latitude)),
        Value::Integer(i64::from(record.longitude)),
    ]);
    values.extend(
        record
            .text
            .into_iter()
            .map(|v| v.map_or(Value::Null, Value::Text)),
    );
    rows.push(values)
}
pub(crate) fn emit(db: &Connection, stage: &Path, manifest: &mut Manifest) -> Result<()> {
    let mut query = db.prepare_cached("SELECT * FROM observations ORDER BY key COLLATE BINARY,source COLLATE BINARY,source_id COLLATE BINARY,name COLLATE BINARY")?;
    let records = query.query_map([], |row| {
        let mut text = std::array::from_fn(|_| None);
        for (i, value) in text.iter_mut().enumerate() {
            *value = row.get(6 + i)?;
        }
        Ok((
            row.get::<_, String>(0)?,
            Observation {
                places: [row.get(1)?, row.get(2)?, row.get(3)?],
                latitude: row.get(4)?,
                longitude: row.get(5)?,
                text,
            },
        ))
    })?;
    let (kind, encoder): (&str, Encoder) = if manifest.family == "phone" {
        ("trie", thereabouts_core::format::trie::encode_entries)
    } else {
        ("exact", encode_entries)
    };
    let mut entries = Vec::new();
    let mut size = 0;
    let mut shard = 0;
    for entry in records {
        let entry = entry?;
        let bytes = entry.0.len()
            + 128
            + entry
                .1
                .text
                .iter()
                .flatten()
                .map(|s| s.len() + 8)
                .sum::<usize>();
        ensure(bytes <= 1024 * 1024, "Forward row exceeds 1 MiB")?;
        if size + bytes > 4 * 1024 * 1024 && !entries.is_empty() {
            add(
                stage,
                manifest,
                &format!("{kind}-{shard:05}.bin"),
                kind,
                &encoder(&entries)?,
            )?;
            entries.clear();
            size = 0;
            shard += 1;
        }
        size += bytes;
        entries.push(entry);
    }
    // Empty indexes are explicit, so a missing shard cannot silently become a miss.
    add(
        stage,
        manifest,
        &format!("{kind}-{shard:05}.bin"),
        kind,
        &encoder(&entries)?,
    )
}

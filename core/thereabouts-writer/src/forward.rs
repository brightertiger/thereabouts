//! Bounded typed staging and emission for forward source associations.
use crate::{
    Error, Result, arrow::Row, catalogue, format::observation::Observation, inserts::Inserts,
};
use rusqlite::{Connection, OptionalExtension, types::Value};
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
        identity: None,
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

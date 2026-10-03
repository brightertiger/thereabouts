//! Intern large lookup sources before sorting, so disk staging does not repeat evidence JSON.
use crate::{Result, compact, dictionaries::Dictionaries, inserts::Inserts};
use rusqlite::{Connection, types::Value};
use thereabouts_core::format::observation::Observation;
pub(crate) struct Packed<'a> {
    dict: Dictionaries<'a>,
    inserts: Inserts<'a>,
    family: &'static str,
}
impl<'a> Packed<'a> {
    pub(crate) fn new(db: &'a Connection, family: &'static str) -> Result<Self> {
        db.execute_batch("CREATE TABLE packed_observations(key BLOB,location INTEGER,source INTEGER,identity INTEGER,line INTEGER,scheme INTEGER,details INTEGER,sort_source TEXT,sort_id TEXT,sort_name TEXT)")?;
        Ok(Self {
            dict: Dictionaries::new(db)?,
            inserts: Inserts::new(db, "INSERT INTO packed_observations", 10),
            family,
        })
    }
    pub(crate) fn push(&mut self, key: Value, record: &Observation) -> Result<()> {
        let (location, fields) = compact::encode_record(&self.dict, record, self.family)?;
        let mut row = vec![key, integer(location)?];
        for i in [0, 1, 2, 4, 5] {
            row.push(integer(*fields.get(i).ok_or_else(|| {
                crate::Error::Input("Invalid staged evidence".into())
            })?)?);
        }
        for value in record.text.iter().take(3) {
            row.push(if self.family == "ip" {
                Value::Null
            } else {
                value.clone().map_or(Value::Null, Value::Text)
            });
        }
        self.inserts.push(row)
    }
    pub(crate) fn finish(&mut self) -> Result<()> {
        self.inserts.flush()
    }
}
fn integer(value: u64) -> Result<Value> {
    Ok(Value::Integer(i64::try_from(value).map_err(|_| {
        crate::Error::Input("Dictionary exceeds SQLite integer range".into())
    })?))
}
pub(crate) fn numeric(row: &rusqlite::Row<'_>) -> rusqlite::Result<(u64, Vec<u64>)> {
    Ok((
        row.get(1)?,
        vec![
            row.get(2)?,
            row.get(3)?,
            row.get(4)?,
            0,
            row.get(5)?,
            row.get(6)?,
        ],
    ))
}

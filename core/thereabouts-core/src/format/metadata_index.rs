//! Small indexes refer to metadata rows without cloning their provenance payloads.
use super::metadata::Metadata;
use crate::{Error, Result, error::ensure};
use serde_json::Value;
use std::collections::{HashMap, HashSet};

#[derive(Debug)]
pub(crate) struct MetadataIndex {
    pub(crate) countries: HashMap<String, usize>,
    pub(crate) subdivisions: HashMap<String, usize>,
    pub(crate) zone_countries: HashMap<String, HashSet<String>>,
}
impl MetadataIndex {
    pub(crate) fn build(metadata: &Metadata) -> Result<Self> {
        let mut zone_countries: HashMap<String, HashSet<String>> = HashMap::new();
        for row in &metadata.zone_tables {
            let name = text(row, "tzid")?;
            if let Some(codes) = row.get("country_codes").and_then(Value::as_str) {
                zone_countries
                    .entry(name.into())
                    .or_default()
                    .extend(codes.split(',').map(str::trim).map(str::to_owned));
            }
        }
        Ok(Self {
            countries: table(&metadata.countries, "country_code")?,
            subdivisions: table(&metadata.subdivisions, "code")?,
            zone_countries,
        })
    }
}
fn table(rows: &[Value], key: &str) -> Result<HashMap<String, usize>> {
    let mut index = HashMap::new();
    for (i, row) in rows.iter().enumerate() {
        let code = text(row, key)?;
        text(row, "name")?;
        ensure(
            index.insert(code.into(), i).is_none(),
            "Repeated metadata code",
        )?;
    }
    Ok(index)
}
pub(crate) fn text<'a>(row: &'a Value, key: &str) -> Result<&'a str> {
    row.get(key)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| Error::Corrupt(format!("Missing metadata {key}")))
}

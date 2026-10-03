//! Golden side tables retain nullable source fields without type coercion.
use crate::{Result, error::ensure};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Metadata tables preserve source rows and timezone overlaps without precedence.
#[derive(Debug, Default, Serialize, Deserialize)]
pub struct Metadata {
    pub countries: Vec<Value>,
    pub subdivisions: Vec<Value>,
    pub zone_tables: Vec<Value>,
    pub timezone_sets: Vec<Vec<String>>,
}
impl Metadata {
    /// Validate fields used by lookup and preserve unknown source metadata.
    pub fn validate(&self) -> Result<()> {
        ensure(
            self.timezone_sets.first() == Some(&vec![]),
            "Missing null timezone set",
        )?;
        for (index, names) in self.timezone_sets.iter().enumerate() {
            ensure(
                (index == 0 || !names.is_empty())
                    && names.windows(2).all(|p| p[0] < p[1])
                    && names.iter().all(|n| !n.is_empty()),
                "Invalid timezone set",
            )?;
        }
        for (rows, key, fields) in [
            (
                &self.countries,
                "country_code",
                "country_code alpha3 numeric name calling_code currency languages tld continent m49 region_code region_name subregion_code subregion_name intermediate_region_code intermediate_region_name",
            ),
            (
                &self.subdivisions,
                "code",
                "code code_system country_code name type parent_code geoname_id name_ascii",
            ),
            (
                &self.zone_tables,
                "tzid",
                "table tzid country_codes comments coordinates_raw h3",
            ),
        ] {
            for row in rows {
                ensure(
                    row.is_object() && row[key].as_str().is_some_and(|s| !s.is_empty()),
                    "Missing metadata row identity",
                )?;
                for field in fields.split_whitespace().chain("source source_id source_release license provenance country_id place_id link_status link_method".split_whitespace()) {
                    ensure(row[field].is_null() || row[field].is_string(), "Invalid metadata string")?;
                }
            }
        }
        Ok(())
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn invalid_metadata_never_silently_loses_a_country_code() {
        let mut metadata = Metadata {
            timezone_sets: vec![vec![]],
            ..Metadata::default()
        };
        assert!(metadata.validate().is_ok());
        metadata
            .countries
            .push(serde_json::json!({"country_code":7}));
        assert!(metadata.validate().is_err());
    }
}

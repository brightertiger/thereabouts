//! Geographic tuples and optional source evidence projection.
use super::{Compact, first};
use crate::{
    Error, Result,
    error::ensure,
    format::{container::index, observation::Observation},
};
impl Compact {
    #[allow(clippy::indexing_slicing)] // Tuple lengths are checked before every fixed-field access.
    pub(super) fn record(
        &self,
        location: u64,
        identity: u64,
        role: &str,
        row: usize,
        evidence: bool,
        count: usize,
    ) -> Result<Observation> {
        ensure(location != 0, "Null source location")?;
        let location = self.table("locations")?.row(index(location)?)?;
        ensure(location.len() == 4, "Invalid location tuple")?;
        let geo = self.table("geographies")?.row(index(first(&location)?)?)?;
        ensure(geo.len() == 7, "Invalid geographic tuple")?;
        let mut places = [0; 3];
        for (target, value) in places.iter_mut().zip(geo.iter().copied()) {
            *target = u32::try_from(value)
                .map_err(|_| Error::Corrupt("Invalid geography reference".into()))?;
        }
        let mut record = Observation {
            fallback: [
                self.text(geo[3])?,
                self.text(geo[4])?,
                self.text(geo[5])?,
                self.text(geo[6])?,
            ],
            identity: Some(identity),
            places,
            latitude: coordinate(&location, 1)?,
            longitude: coordinate(&location, 2)?,
            text: std::array::from_fn(|_| None),
        };
        if evidence {
            let fields = self.table(role)?.row(row)?;
            ensure(fields.len() == 6, "Invalid evidence tuple")?;
            record.text[0] = self.text(fields[0])?;
            record.text[1] = self.text(fields[1])?.map(|prefix| {
                if fields[2] == 0 {
                    prefix
                } else {
                    format!("{prefix}{}", fields[2] - 1)
                }
            });
            ensure(
                record
                    .text
                    .iter()
                    .take(2)
                    .all(|v| v.as_ref().is_some_and(|s| !s.is_empty())),
                "Missing source evidence identity",
            )?;
            record.text[2] = self.text(location[3])?;
            record.text[3] = self.text(fields[3])?;
            record.text[4] = self.text(fields[4])?;
            record.text[5] = self.details(fields[5])?;
        }

        record.validate(count)?;
        Ok(record)
    }
    pub(super) fn details(&self, ordinal: u64) -> Result<Option<String>> {
        if ordinal == 0 {
            return Ok(None);
        }
        let values = self.table("details")?.row(index(ordinal)?)?;
        ensure(
            values.len() == self.schema.detail_fields.len(),
            "Invalid details tuple",
        )?;
        let mut details = serde_json::Map::new();
        for (name, value) in self.schema.detail_fields.iter().zip(values) {
            ensure(value != 1, "Missing tagged scalar string")?;
            if let Some(text) = self.text(value >> 1)? {
                let scalar = if value & 1 == 1 {
                    serde_json::Value::String(text)
                } else {
                    let scalar: serde_json::Value = serde_json::from_str(&text)?;
                    ensure(
                        scalar.is_null() || scalar.is_boolean() || scalar.is_number(),
                        "Invalid non-string detail scalar",
                    )?;
                    scalar
                };
                details.insert(name.clone(), scalar);
            }
        }
        Ok(Some(serde_json::to_string(&details)?))
    }
}
fn coordinate(row: &[u64], field: usize) -> Result<i32> {
    row.get(field)
        .copied()
        .and_then(|v| u32::try_from(v).ok())
        .map(u32::cast_signed)
        .ok_or_else(|| Error::Corrupt("Invalid coordinate field".into()))
}

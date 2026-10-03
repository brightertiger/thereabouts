//! Eighty-byte place records with a shard-local UTF-8 pool.
use super::container::{Container, encode, index, put, uint};
use crate::{Result, error::ensure, result::Point};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Nullable string fields retain the original catalogue field ordering.
pub const TEXT_FIELDS: [&str; 12] = [
    "place_id",
    "name",
    "name_en",
    "local_name",
    "role",
    "settlement_kind",
    "country_code",
    "code",
    "code_status",
    "parent_method",
    "normalization_method",
    "evidence",
];
/// Pack-global relationship references, in wire order.
pub const REF_FIELDS: [&str; 4] = [
    "country_id",
    "parent_id",
    "sovereign_id",
    "normalized_city_id",
];
/// Decoded record; the same definition feeds reader and writer.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Place {
    pub text: [Option<String>; 12],
    pub refs: [u32; 4],
    pub latitude: i32,
    pub longitude: i32,
    pub population: u32,
    pub timezone: Option<String>,
}
impl Place {
    /// Null coordinates use a sentinel outside geographic degree ranges.
    #[must_use]
    pub fn point(&self) -> Option<Point> {
        (self.latitude != i32::MIN).then(|| Point {
            lat: f64::from(self.latitude) / 1e6,
            lon: f64::from(self.longitude) / 1e6,
        })
    }
    /// Public identity and required display fields have already been validated.
    #[must_use]
    pub fn field(&self, index: usize) -> &str {
        self.text[index].as_deref().unwrap_or("")
    }
    /// Check geographic bounds, required text and catalogue relationships.
    pub fn validate(&self, total: usize) -> Result<()> {
        ensure(
            [0, 1, 4, 5, 6, 11]
                .iter()
                .all(|i| self.text[*i].as_ref().is_some_and(|s| !s.is_empty())),
            "Missing required catalogue text",
        )?;
        ensure(
            self.refs.iter().all(|r| *r as usize <= total),
            "Dangling catalogue relationship",
        )?;
        ensure(
            (self.latitude == i32::MIN && self.longitude == i32::MIN)
                || ((-90_000_000..=90_000_000).contains(&self.latitude)
                    && (-180_000_000..=180_000_000).contains(&self.longitude)),
            "Invalid catalogue point",
        )?;
        let _: serde_json::Value = serde_json::from_str(self.field(11))?;
        Ok(())
    }
}
/// Encode first-use string references; zero always means null.
pub fn encode_places(places: &[Place]) -> Result<Vec<u8>> {
    let mut refs = BTreeMap::new();
    let mut offsets = vec![0_u64, 0];
    let mut text = vec![];
    let mut records = vec![];
    for place in places {
        for value in place.text.iter().chain(std::iter::once(&place.timezone)) {
            if let Some(s) = value
                && !refs.contains_key(s)
            {
                refs.insert(s.clone(), offsets.len() - 1);
                text.extend_from_slice(s.as_bytes());
                offsets.push(text.len() as u64);
            }
        }
        for value in &place.text {
            put(
                &mut records,
                value.as_ref().map_or(0, |s| refs[s] as u64),
                4,
            );
        }
        for r in place.refs {
            put(&mut records, u64::from(r), 4);
        }
        records.extend_from_slice(&place.latitude.to_le_bytes());
        records.extend_from_slice(&place.longitude.to_le_bytes());
        put(&mut records, u64::from(place.population), 4);
        put(
            &mut records,
            place.timezone.as_ref().map_or(0, |s| refs[s] as u64),
            4,
        );
    }
    let mut offset_bytes = vec![];
    for o in offsets {
        put(&mut offset_bytes, o, 8);
    }
    encode(2, &[(&records, 80), (&offset_bytes, 8), (&text, 1)])
}
/// Raw catalogue storage: record/string bytes are retained without allocating places.
#[derive(Debug)]
pub(crate) struct Catalogue {
    container: Container,
}
impl Catalogue {
    pub(crate) fn decode(bytes: Vec<u8>) -> Result<Self> {
        let container = Container::decode(bytes, 2, &[80, 8, 1])?;
        let pool = container.section(2);
        let mut previous = 0;
        let offsets = container.section(1);
        ensure(
            offsets.len() >= 16 && uint(offsets, 0, 8)? == 0 && uint(offsets, 8, 8)? == 0,
            "Invalid null string offset",
        )?;
        for position in (0..offsets.len()).step_by(8) {
            let offset = index(uint(offsets, position, 8)?)?;
            let text = pool
                .get(previous..offset)
                .ok_or_else(|| crate::Error::Corrupt("Invalid string offsets".into()))?;
            std::str::from_utf8(text).map_err(|_| crate::Error::Corrupt("Invalid UTF-8".into()))?;
            previous = offset;
        }
        ensure(previous == pool.len(), "Invalid terminal string offset")?;
        Ok(Self { container })
    }
    pub(crate) fn bytes(&self) -> usize {
        self.container.bytes.len()
    }
    pub(crate) fn len(&self) -> usize {
        self.container.section(0).len() / 80
    }
    fn string(&self, reference: u64) -> Result<Option<String>> {
        let position = index(reference)?
            .checked_mul(8)
            .ok_or_else(|| crate::Error::Corrupt("String reference overflow".into()))?;
        let offsets = self.container.section(1);
        let start = index(uint(offsets, position, 8)?)?;
        let end = index(uint(offsets, position + 8, 8)?)?;
        let text = self
            .container
            .section(2)
            .get(start..end)
            .ok_or_else(|| crate::Error::Corrupt("Dangling string reference".into()))?;
        let text =
            std::str::from_utf8(text).map_err(|_| crate::Error::Corrupt("Invalid UTF-8".into()))?;
        Ok((reference != 0).then(|| text.to_owned()))
    }
    pub(crate) fn place(&self, index: usize) -> Result<Place> {
        let start = index
            .checked_mul(80)
            .ok_or_else(|| crate::Error::Corrupt("Record overflow".into()))?;
        let row = self
            .container
            .section(0)
            .get(start..start + 80)
            .ok_or_else(|| crate::Error::Corrupt("Dangling place reference".into()))?;
        let mut text = std::array::from_fn(|_| None);
        let mut refs = [0; 4];
        for (i, value) in text.iter_mut().enumerate() {
            *value = self.string(uint(row, i * 4, 4)?)?;
        }
        for (i, value) in refs.iter_mut().enumerate() {
            *value = u32::try_from(uint(row, 48 + i * 4, 4)?).expect("four bytes");
        }
        Ok(Place {
            text,
            refs,
            latitude: i32::from_le_bytes(row[64..68].try_into().expect("fixed record")),
            longitude: i32::from_le_bytes(row[68..72].try_into().expect("fixed record")),
            population: u32::try_from(uint(row, 72, 4)?).expect("four bytes"),
            timezone: self.string(uint(row, 76, 4)?)?,
        })
    }
}
/// Full verification materializes one shard at a time; runtime decodes on demand.
pub fn decode(bytes: Vec<u8>) -> Result<Vec<Place>> {
    let catalogue = Catalogue::decode(bytes)?;
    (0..catalogue.len()).map(|i| catalogue.place(i)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn invalid_point_and_dangling_reference() {
        let mut place = Place {
            text: std::array::from_fn(|i| Some(if i == 11 { "{}".into() } else { "x".into() })),
            refs: [0; 4],
            latitude: i32::MIN,
            longitude: i32::MIN,
            population: 0,
            timezone: None,
        };
        assert!(place.validate(1).is_ok());
        assert!(place.point().is_none());
        place.longitude = 0;
        assert!(place.validate(1).is_err());
        place.longitude = i32::MIN;
        place.refs[0] = 2;
        assert!(place.validate(1).is_err());
    }
}

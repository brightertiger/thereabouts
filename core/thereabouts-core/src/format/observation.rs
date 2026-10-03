//! Shared 44-byte forward observation layout, used by exact, prefix and interval indexes.
use super::container::{FileShard, index, put, uint};
use crate::{Error, Result, error::ensure, result::Point};
use std::collections::BTreeMap;
/// String fields in the observation record, after the geography and point fields.
pub const FIELDS: [&str; 6] = ["source", "source_id", "name", "code", "scheme", "details"];
/// One source association. Geography references are pack-global catalogue references.
#[derive(Clone, Debug)]
pub struct Observation {
    /// Country, subdivision and canonical-city references; zero means absent.
    pub places: [u32; 3],
    /// Source latitude in microdegrees, or `i32::MIN` when unlocated.
    pub latitude: i32,
    /// Source longitude in microdegrees, paired with latitude's sentinel.
    pub longitude: i32,
    /// Published source fields in FIELDS order; details is optional JSON text.
    pub text: [Option<String>; 6],
}
impl Observation {
    /// Preserve the source point independently of its associated city's anchor.
    #[must_use]
    pub fn point(&self) -> Option<Point> {
        (self.latitude != i32::MIN).then(|| Point {
            lat: f64::from(self.latitude) / 1e6,
            lon: f64::from(self.longitude) / 1e6,
        })
    }
    /// Validate references, source identity and optional coordinate pair.
    pub fn validate(&self, count: usize) -> Result<()> {
        ensure(
            self.places.iter().all(|p| *p as usize <= count),
            "Dangling observation place",
        )?;
        ensure(
            self.text
                .iter()
                .take(2)
                .all(|s| s.as_ref().is_some_and(|s| !s.is_empty())),
            "Missing observation source identity",
        )?;
        ensure(
            (self.latitude == i32::MIN && self.longitude == i32::MIN)
                || ((-90_000_000..=90_000_000).contains(&self.latitude)
                    && (-180_000_000..=180_000_000).contains(&self.longitude)),
            "Invalid observation point",
        )?;
        if let Some(details) = self.text.get(5).and_then(Option::as_deref) {
            let _: serde_json::Value = serde_json::from_str(details)?;
        }
        Ok(())
    }
}
/// First-use string interning shared by observation writers.
#[derive(Default)]
pub struct Strings {
    references: BTreeMap<String, u32>,
    /// String starts, including the empty null entry.
    pub offsets: Vec<u8>,
    /// Concatenated UTF-8 bytes.
    pub bytes: Vec<u8>,
}
impl Strings {
    /// Start with the required zero-length null slot.
    #[must_use]
    pub fn new() -> Self {
        Self {
            offsets: vec![0; 16],
            ..Self::default()
        }
    }
    /// Intern one nullable string without changing first-use order.
    pub fn reference(&mut self, text: Option<&str>) -> Result<u32> {
        let Some(text) = text else {
            return Ok(0);
        };
        if let Some(reference) = self.references.get(text) {
            return Ok(*reference);
        }
        let reference = u32::try_from(self.offsets.len() / 8 - 1)
            .map_err(|_| Error::Input("Too many strings".into()))?;
        self.bytes.extend_from_slice(text.as_bytes());
        put(&mut self.offsets, self.bytes.len() as u64, 8);
        self.references.insert(text.into(), reference);
        Ok(reference)
    }
}
/// Append exactly one 44-byte record.
pub fn encode(record: &Observation, strings: &mut Strings, bytes: &mut Vec<u8>) -> Result<()> {
    for value in record.places {
        put(bytes, u64::from(value), 4);
    }
    bytes.extend(record.latitude.to_le_bytes());
    bytes.extend(record.longitude.to_le_bytes());
    for value in &record.text {
        put(bytes, u64::from(strings.reference(value.as_deref())?), 4);
    }
    Ok(())
}
pub(crate) fn string(shard: &FileShard, offsets: usize, reference: u64) -> Result<Option<String>> {
    if reference == 0 {
        return Ok(None);
    }
    let start = index(reference)?
        .checked_mul(8)
        .ok_or_else(|| Error::Corrupt("String reference overflow".into()))?;
    let pair = shard.range(offsets, start, 16)?;
    let a = index(uint(&pair, 0, 8)?)?;
    let b = index(uint(&pair, 8, 8)?)?;
    let length = b
        .checked_sub(a)
        .ok_or_else(|| Error::Corrupt("Invalid string offsets".into()))?;
    String::from_utf8(shard.range(offsets + 1, a, length)?)
        .map(Some)
        .map_err(|_| Error::Corrupt("Invalid UTF-8".into()))
}
pub(crate) fn read(
    shard: &FileShard,
    section: usize,
    row: usize,
    count: usize,
) -> Result<Observation> {
    let position = row
        .checked_mul(44)
        .ok_or_else(|| Error::Corrupt("Record overflow".into()))?;
    let bytes = shard.range(section, position, 44)?;
    let mut places = [0; 3];
    for (i, reference) in places.iter_mut().enumerate() {
        *reference = u32::try_from(uint(&bytes, i * 4, 4)?)
            .map_err(|_| Error::Corrupt("Invalid place ref".into()))?;
    }
    let mut text = std::array::from_fn(|_| None);
    for (i, field) in text.iter_mut().enumerate() {
        *field = string(shard, section + 1, uint(&bytes, 20 + i * 4, 4)?)?;
    }
    let record = Observation {
        places,
        latitude: u32::try_from(uint(&bytes, 12, 4)?)
            .map_err(|_| Error::Corrupt("Invalid latitude".into()))?
            .cast_signed(),
        longitude: u32::try_from(uint(&bytes, 16, 4)?)
            .map_err(|_| Error::Corrupt("Invalid longitude".into()))?
            .cast_signed(),
        text,
    };
    record.validate(count)?;
    Ok(record)
}

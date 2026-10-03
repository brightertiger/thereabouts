//! Eighty-byte place records with record-local UTF-8 blocks.
use super::container::{Container, FileShard, encode, index, put, uint};
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
    /// Nullable string fields in `TEXT_FIELDS` order; required fields are checked on decode.
    pub text: [Option<String>; 12],
    /// Pack-global relationships in `REF_FIELDS` order; zero is null.
    pub refs: [u32; 4],
    /// Latitude in microdegrees, or `i32::MIN` when the anchor is unknown.
    pub latitude: i32,
    /// Longitude in microdegrees, sharing latitude's unknown sentinel.
    pub longitude: i32,
    /// Published population; zero represents unknown.
    pub population: u32,
    /// Single published zone at the catalogue anchor, when available.
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
        self.text
            .get(index)
            .and_then(Option::as_deref)
            .unwrap_or("")
    }
    /// Check geographic bounds, required text and catalogue relationships.
    pub fn validate(&self, total: usize) -> Result<()> {
        ensure(
            [0, 1, 4, 5, 6].iter().all(|i| {
                self.text
                    .get(*i)
                    .and_then(Option::as_ref)
                    .is_some_and(|s| !s.is_empty())
            }),
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
        if let Some(evidence) = self.text.get(11).and_then(Option::as_deref) {
            let _: serde_json::Value = serde_json::from_str(evidence)?;
        }
        Ok(())
    }
}
/// Maximum bytes in one record's strings, including evidence. The sample's
/// largest record is below 4 KiB; 64 KiB leaves headroom without shard-sized reads.
pub const MAX_RECORD_STRING_BYTES: usize = 64 * 1024;

/// Encode record-local strings in first-use order, with cold evidence last.
/// Identical hot strings share a reference only within the same record.
#[allow(clippy::indexing_slicing)] // Fixed wire fields; loop indices are bounded by the 13-slot schema.
pub fn encode_places(places: &[Place]) -> Result<Vec<u8>> {
    let mut offsets = vec![0_u64, 0];
    let mut text = vec![];
    let mut records = vec![];
    for place in places {
        let mut refs = BTreeMap::new();
        let mut references = [0; 13];
        let start = text.len();
        for i in (0..11).chain([12, 11]) {
            let value = if i == 12 {
                &place.timezone
            } else {
                &place.text[i]
            };
            if let Some(value) = value {
                // Evidence always has its own final slot, even if equal to a hot string.
                let reference = if i == 11 {
                    None
                } else {
                    refs.get(value).copied()
                };
                let reference = reference.unwrap_or_else(|| {
                    let reference = offsets.len() as u64 - 1;
                    text.extend_from_slice(value.as_bytes());
                    offsets.push(text.len() as u64);
                    refs.insert(value, reference);
                    reference
                });
                references[i] = reference;
            }
        }
        ensure(
            text.len() - start <= MAX_RECORD_STRING_BYTES,
            "Oversized record string block",
        )?;
        for reference in &references[..12] {
            put(&mut records, *reference, 4);
        }
        for r in place.refs {
            put(&mut records, u64::from(r), 4);
        }
        records.extend_from_slice(&place.latitude.to_le_bytes());
        records.extend_from_slice(&place.longitude.to_le_bytes());
        put(&mut records, u64::from(place.population), 4);
        put(&mut records, references[12], 4);
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
        let catalogue = Self { container };
        catalogue.validate_locality()?;
        Ok(catalogue)
    }
    fn validate_locality(&self) -> Result<()> {
        let offsets = self.container.section(1);
        let mut next = 1;
        for row in self.container.section(0).as_chunks::<80>().0 {
            let (first, last) = string_bounds(row)?;
            ensure(first == next, "Catalogue strings cross record boundaries")?;
            let start = uint(offsets, index(first)? * 8, 8)?;
            let end = uint(offsets, index(last + 1)? * 8, 8)?;
            ensure(
                end - start <= MAX_RECORD_STRING_BYTES as u64,
                "Oversized record string block",
            )?;
            next = last + 1;
        }
        ensure(
            index(next)? + 1 == offsets.len() / 8,
            "Unused catalogue strings",
        )
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
        decode_record(row, |reference| self.string(reference))
    }
}
fn decode_record(
    row: &[u8],
    mut string: impl FnMut(u64) -> Result<Option<String>>,
) -> Result<Place> {
    let mut text = std::array::from_fn(|_| None);
    let mut refs = [0; 4];
    for (i, value) in text.iter_mut().enumerate() {
        *value = string(uint(row, i * 4, 4)?)?;
    }
    for (i, value) in refs.iter_mut().enumerate() {
        *value = u32::try_from(uint(row, 48 + i * 4, 4)?)
            .map_err(|_| crate::Error::Corrupt("Invalid u32".into()))?;
    }
    Ok(Place {
        text,
        refs,
        latitude: u32::try_from(uint(row, 64, 4)?)
            .map_err(|_| crate::Error::Corrupt("Invalid latitude".into()))?
            .cast_signed(),
        longitude: u32::try_from(uint(row, 68, 4)?)
            .map_err(|_| crate::Error::Corrupt("Invalid longitude".into()))?
            .cast_signed(),
        population: u32::try_from(uint(row, 72, 4)?)
            .map_err(|_| crate::Error::Corrupt("Invalid u32".into()))?,
        timezone: string(uint(row, 76, 4)?)?,
    })
}
/// Validate pool sentinels without loading offsets or strings into memory.
pub(crate) fn validate_header(shard: &FileShard) -> Result<()> {
    let length = shard.len(1)?;
    ensure(length >= 16, "Missing string offsets")?;
    let initial = shard.range(1, 0, 16)?;
    ensure(
        initial.iter().all(|b| *b == 0),
        "Invalid null string offset",
    )?;
    ensure(
        index(uint(&shard.range(1, length - 8, 8)?, 0, 8)?)? == shard.len(2)?,
        "Invalid terminal string offset",
    )
}
fn string_bounds(row: &[u8]) -> Result<(u64, u64)> {
    let mut refs = std::collections::BTreeSet::new();
    let evidence = uint(row, 44, 4)?;
    for offset in (0..48).step_by(4).chain(std::iter::once(76)) {
        let reference = uint(row, offset, 4)?;
        if reference != 0 {
            ensure(
                offset == 44 || reference != evidence,
                "Evidence shares a hot string reference",
            )?;
            refs.insert(reference);
        }
    }
    let first = refs.first().copied().unwrap_or(0);
    let last = refs.last().copied().unwrap_or(0);
    ensure(
        first != 0 && last - first + 1 == refs.len() as u64,
        "Nonlocal record strings",
    )?;
    ensure(
        evidence == 0 || evidence == last,
        "Evidence must end the record string block",
    )?;
    Ok((first, last))
}

/// Coalesce one record's requested offsets and text into two positioned reads.
/// Evidence is excluded from the reference span unless the caller requests it.
pub(crate) fn read_place(shard: &FileShard, record: usize, evidence: bool) -> Result<Place> {
    let offset = record
        .checked_mul(80)
        .ok_or_else(|| crate::Error::Corrupt("Record overflow".into()))?;
    let mut row = shard.range(0, offset, 80)?;
    string_bounds(&row)?;
    if !evidence {
        row.get_mut(44..48)
            .ok_or_else(|| crate::Error::Corrupt("Missing evidence slot".into()))?
            .fill(0);
    }
    let (first, last) = string_bounds(&row)?;
    let position = index(first)?
        .checked_mul(8)
        .ok_or_else(|| crate::Error::Corrupt("String offset overflow".into()))?;
    let length = index(last - first + 2)?
        .checked_mul(8)
        .ok_or_else(|| crate::Error::Corrupt("String span overflow".into()))?;
    ensure(length <= 14 * 8, "Oversized record offset span")?;
    let offsets = shard.range(1, position, length)?;
    let text_start = index(uint(&offsets, 0, 8)?)?;
    let text_end = index(uint(&offsets, length - 8, 8)?)?;
    let length = text_end
        .checked_sub(text_start)
        .ok_or_else(|| crate::Error::Corrupt("Reversed text span".into()))?;
    ensure(
        length <= MAX_RECORD_STRING_BYTES,
        "Oversized record string block",
    )?;
    let text = shard.range(2, text_start, length)?;
    decode_record(&row, |reference| {
        if reference == 0 {
            return Ok(None);
        }
        let position = index(reference - first)? * 8;
        let start = index(uint(&offsets, position, 8)?)?
            .checked_sub(text_start)
            .ok_or_else(|| crate::Error::Corrupt("Invalid string start".into()))?;
        let end = index(uint(&offsets, position + 8, 8)?)?
            .checked_sub(text_start)
            .ok_or_else(|| crate::Error::Corrupt("Invalid string end".into()))?;
        let value = text
            .get(start..end)
            .ok_or_else(|| crate::Error::Corrupt("Invalid string span".into()))?;
        std::str::from_utf8(value)
            .map(|v| Some(v.to_owned()))
            .map_err(|_| crate::Error::Corrupt("Invalid UTF-8".into()))
    })
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
    fn record_reads_are_bounded_and_evidence_is_separate() {
        let mut places = vec![];
        for i in 0..1000 {
            places.push(Place {
                text: std::array::from_fn(|field| {
                    Some(if field == 11 {
                        format!("{{\"padding\":\"{}\",\"id\":{i}}}", "x".repeat(2048))
                    } else {
                        format!("field{field}:record{i}")
                    })
                }),
                refs: [0; 4],
                latitude: i32::MIN,
                longitude: i32::MIN,
                population: 0,
                timezone: Some("Shared/Zone".into()),
            });
        }
        let bytes = encode_places(&places).unwrap();
        let decoded = decode(bytes.clone()).unwrap();
        assert_eq!(decoded[999].text, places[999].text);
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("large.bin");
        std::fs::write(&path, bytes).unwrap();
        let shard = FileShard::open(&path, 2, &[80, 8, 1]).unwrap();
        for evidence in [false, true] {
            shard.reads.lock().unwrap().clear();
            let place = read_place(&shard, 999, evidence).unwrap();
            assert_eq!(place.timezone.as_deref(), Some("Shared/Zone"));
            assert_eq!(place.text[11].is_some(), evidence);
            let reads = shard.reads.lock().unwrap();
            assert_eq!(reads.len(), 3);
            assert_eq!(reads[0], 80);
            assert!(reads[1] <= 112);
            assert!(reads[2] <= if evidence { 4096 } else { 256 });
        }
        places[0].text[11] = Some("x".repeat(MAX_RECORD_STRING_BYTES));
        assert!(encode_places(&places[..1]).is_err());
    }
    #[test]
    fn cross_record_string_reference_is_rejected() {
        let place = Place {
            text: std::array::from_fn(|i| Some(if i == 11 { "{}".into() } else { "x".into() })),
            refs: [0; 4],
            latitude: i32::MIN,
            longitude: i32::MIN,
            population: 0,
            timezone: None,
        };
        let mut bytes = encode_places(&[place.clone(), place]).unwrap();
        let start = index(uint(&bytes, 40, 8).unwrap()).unwrap();
        // The second record cannot reuse the first record's "x" reference.
        bytes[start + 80..start + 84].copy_from_slice(&1u32.to_le_bytes());
        assert!(decode(bytes).is_err());
        let mut bytes = encode_places(&[Place {
            text: std::array::from_fn(|_| Some("{}".into())),
            refs: [0; 4],
            latitude: i32::MIN,
            longitude: i32::MIN,
            population: 0,
            timezone: None,
        }])
        .unwrap();
        bytes[start + 44..start + 48].copy_from_slice(&1u32.to_le_bytes());
        assert!(decode(bytes).is_err());
    }
    #[test]
    fn record_miss_does_not_validate_unrelated_strings() {
        let first = Place {
            text: std::array::from_fn(|i| Some(if i == 11 { "{}".into() } else { "first".into() })),
            refs: [0; 4],
            latitude: i32::MIN,
            longitude: i32::MIN,
            population: 0,
            timezone: None,
        };
        let mut second = first.clone();
        second.text[0] = Some("second".into());
        let mut bytes = encode_places(&[first, second]).unwrap();
        let start = bytes.windows(6).position(|s| s == b"second").unwrap();
        bytes[start] = 255;
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("catalogue.bin");
        std::fs::write(&path, &bytes).unwrap();
        let shard = FileShard::open(&path, 2, &[80, 8, 1]).unwrap();
        validate_header(&shard).unwrap();
        assert_eq!(read_place(&shard, 0, false).unwrap().field(0), "first");
        assert!(read_place(&shard, 1, false).is_err());
        assert!(Catalogue::decode(bytes).is_err());
    }
    #[test]
    fn malformed_evidence_is_cold_until_requested() {
        let place = Place {
            text: std::array::from_fn(|i| {
                Some(if i == 11 {
                    "{broken".into()
                } else {
                    "query".into()
                })
            }),
            refs: [0; 4],
            latitude: i32::MIN,
            longitude: i32::MIN,
            population: 0,
            timezone: None,
        };
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("catalogue.bin");
        std::fs::write(&path, encode_places(&[place]).unwrap()).unwrap();
        let shard = FileShard::open(&path, 2, &[80, 8, 1]).unwrap();
        let hot = read_place(&shard, 0, false).unwrap();
        hot.validate(1).unwrap();
        assert!(hot.text[11].is_none());
        assert!(read_place(&shard, 0, true).unwrap().validate(1).is_err());
    }
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

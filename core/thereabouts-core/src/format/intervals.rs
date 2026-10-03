//! Inclusive IP intervals: binary search reads fixed-width bounds from retained files.
use super::{
    container::{FileShard, encode},
    observation::{self, Observation, Strings},
};
use crate::{Error, Result, error::ensure};
use std::path::Path;
/// Version plus a network-order numeric address keeps IPv4 and IPv6 separate.
pub type Address = (u8, u128);
/// Published inclusive endpoints for one observation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Bounds {
    /// IP version, four or six.
    pub version: u8,
    /// Inclusive start, with zero upper 96 bits for IPv4.
    pub first: u128,
    /// Inclusive end in the same address family.
    pub last: u128,
}
impl Bounds {
    /// Stable SQLite sorting key, not an on-wire textual address.
    #[must_use]
    pub fn key(self) -> String {
        format!("{:02x}{:032x}{:032x}", self.version, self.first, self.last)
    }
    fn valid(self) -> Result<()> {
        ensure(
            matches!(self.version, 4 | 6)
                && self.first <= self.last
                && (self.version != 4 || self.last <= u128::from(u32::MAX)),
            "Invalid IP interval",
        )
    }
}
/// Decode the stable staging key without changing its inclusive source bounds.
pub fn from_key(key: &str) -> Result<Bounds> {
    let parse = |a, b| {
        key.get(a..b)
            .and_then(|s| u128::from_str_radix(s, 16).ok())
            .ok_or_else(|| Error::Corrupt("Invalid staged IP bounds".into()))
    };
    ensure(key.len() == 66, "Invalid staged IP key length")?;
    let value = Bounds {
        version: u8::try_from(parse(0, 2)?)
            .map_err(|_| Error::Corrupt("Invalid IP version".into()))?,
        first: parse(2, 34)?,
        last: parse(34, 66)?,
    };
    value.valid()?;
    Ok(value)
}
fn decode(bytes: &[u8]) -> Result<Bounds> {
    ensure(
        bytes.len() == 36 && bytes.get(1..4) == Some(&[0, 0, 0]),
        "Invalid interval record",
    )?;
    let address = |a, b| {
        bytes
            .get(a..b)
            .and_then(|b| b.try_into().ok())
            .map(u128::from_be_bytes)
            .ok_or_else(|| Error::Corrupt("Truncated IP bounds".into()))
    };
    let value = Bounds {
        version: *bytes
            .first()
            .ok_or_else(|| Error::Corrupt("Missing IP version".into()))?,
        first: address(4, 20)?,
        last: address(20, 36)?,
    };
    value.valid()?;
    Ok(value)
}
/// Require strictly increasing, nonoverlapping intervals, including across shard boundaries.
pub fn follows(previous: Option<Bounds>, next: Bounds) -> Result<()> {
    next.valid()?;
    ensure(
        previous.is_none_or(|p| (p.version, p.last) < (next.version, next.first)),
        "Overlapping or unsorted IP intervals",
    )
}
/// Encode sorted intervals with one shared observation per range.
pub fn encode_entries(entries: &[(String, Observation)]) -> Result<Vec<u8>> {
    let mut bounds = Vec::new();
    let mut records = Vec::new();
    let mut strings = Strings::new();
    let mut previous = None;
    for (key, record) in entries {
        let value = from_key(key)?;
        follows(previous, value)?;
        previous = Some(value);
        bounds.extend([value.version, 0, 0, 0]);
        bounds.extend(value.first.to_be_bytes());
        bounds.extend(value.last.to_be_bytes());
        observation::encode(record, &mut strings, &mut records)?;
    }
    encode(
        6,
        &[
            (&bounds, 36),
            (&records, 44),
            (&strings.offsets, 8),
            (&strings.bytes, 1),
        ],
    )
}
/// Only endpoints are held at open; range search performs positioned reads.
#[derive(Debug)]
pub(crate) struct Intervals {
    file: FileShard,
    count: usize,
    pub(crate) span: Option<(Bounds, Bounds)>,
}
impl Intervals {
    pub(crate) fn open(path: &Path) -> Result<Self> {
        let file = FileShard::open(path, 6, &[36, 44, 8, 1])?;
        let count = file.len(0)? / 36;
        ensure(
            file.len(1)? / 44 == count,
            "IP interval/observation count mismatch",
        )?;
        let span = if count == 0 {
            None
        } else {
            let first = decode(&file.range(0, 0, 36)?)?;
            let last = decode(&file.range(0, (count - 1) * 36, 36)?)?;
            if count > 1 {
                follows(Some(first), last)?;
            }
            Some((first, last))
        };
        let null = file.range(2, 0, 16)?;
        ensure(null.iter().all(|b| *b == 0), "Invalid null interval string")?;
        let terminal = file.range(2, file.len(2)? - 8, 8)?;
        ensure(
            super::container::uint(&terminal, 0, 8)? == file.len(3)? as u64,
            "Invalid interval string terminal",
        )?;
        Ok(Self { file, count, span })
    }
    fn bound(&self, row: usize) -> Result<Bounds> {
        decode(&self.file.range(0, row * 36, 36)?)
    }
    pub(crate) fn lookup(&self, address: Address) -> Result<Option<usize>> {
        let Some((first, last)) = self.span else {
            return Ok(None);
        };
        if address < (first.version, first.first) || address > (last.version, last.last) {
            return Ok(None);
        }
        let mut low = 0;
        let mut high = self.count;
        while low < high {
            let mid = low + (high - low) / 2;
            let value = self.bound(mid)?;
            if (value.version, value.first) <= address {
                low = mid + 1;
            } else {
                high = mid;
            }
        }
        if low == 0 {
            return Ok(None);
        }
        let value = self.bound(low - 1)?;
        Ok(
            (value.version == address.0 && value.first <= address.1 && address.1 <= value.last)
                .then_some(low - 1),
        )
    }
    pub(crate) fn record(&self, row: usize, count: usize) -> Result<Observation> {
        observation::read(&self.file, 1, row, count)
    }
    pub(crate) fn verify(&self, count: usize) -> Result<()> {
        let mut previous = None;
        for row in 0..self.count {
            let value = self.bound(row)?;
            follows(previous, value)?;
            previous = Some(value);
            self.record(row, count)?;
        }
        Ok(())
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;
    proptest! {
        #[test]
        fn round_trip_inclusive_bounds(start in 0_u32..u32::MAX-1024, width in 0_u32..1024) {
            let dir=tempfile::tempdir().unwrap();let path=dir.path().join("ip.bin");
            let range=Bounds{version:4,first:u128::from(start),last:u128::from(start+width)};
            let record=Observation{fallback:[None,None,None,None],identity:None,places:[0;3],latitude:i32::MIN,longitude:i32::MIN,text:[Some("s".into()),Some("id".into()),None,None,None,None]};
            std::fs::write(&path,encode_entries(&[(range.key(),record)]).unwrap()).unwrap();
            let index=Intervals::open(&path).unwrap();
            prop_assert_eq!(index.lookup((4,range.first)).unwrap(),Some(0));
            prop_assert_eq!(index.lookup((4,range.last)).unwrap(),Some(0));
            prop_assert_eq!(index.lookup((4,range.last+1)).unwrap(),None);
            prop_assert_eq!(index.lookup((6,range.first)).unwrap(),None);
            index.verify(0).unwrap();
        }
    }
    #[test]
    fn rejects_overlap_and_invalid_ipv4() {
        let a = Bounds {
            version: 4,
            first: 1,
            last: 10,
        };
        assert!(
            follows(
                Some(a),
                Bounds {
                    version: 4,
                    first: 10,
                    last: 20
                }
            )
            .is_err()
        );
        assert!(
            follows(
                None,
                Bounds {
                    version: 4,
                    first: 0,
                    last: 1_u128 << 32
                }
            )
            .is_err()
        );
    }
}

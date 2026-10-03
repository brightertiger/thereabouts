//! Logical base-7 addresses preserve H3 ancestor relationships.
use crate::{Error, Result};
use h3o::{CellIndex, Resolution};

/// First sparse key at a depth below resolution three.
#[must_use]
pub const fn offset(depth: u32) -> u16 {
    [0, 1, 8, 57, 400, 2801][depth as usize]
}
/// Split a validated stored cell into its block and sparse key.
#[must_use]
pub fn address(cell: CellIndex) -> (u32, u16) {
    let value = u64::from(cell);
    let r = u8::from(cell.resolution());
    let mut block = ((value >> 45) & 127) as u32;
    let mut local = 0_u16;
    for level in 1..=r {
        let digit = ((value >> (3 * (15 - level))) & 7) as u16;
        if level <= 3 {
            block = block * 7 + u32::from(digit);
        } else {
            local = local * 7 + digit;
        }
    }
    (block, offset(u32::from(r.saturating_sub(3))) + local)
}
/// Decode a sparse key, rejecting pentagon holes and out-of-range addresses.
pub fn cell_at(mut block: u32, key: u16) -> Result<CellIndex> {
    if block >= 41846 || key > 19607 {
        return Err(Error::Corrupt("Invalid H3 address".into()));
    }
    let mut depth = 0;
    while depth < 5 && offset(depth + 1) <= key {
        depth += 1;
    }
    let mut local = key - offset(depth);
    let mut digits = Vec::new();
    for _ in 0..depth {
        digits.push(u64::from(local % 7));
        local /= 7;
    }
    for _ in 0..3 {
        digits.push(u64::from(block % 7));
        block /= 7;
    }
    let mut value =
        (1 << 59) | (u64::from(3 + depth) << 52) | (u64::from(block) << 45) | ((1 << 45) - 1);
    for (i, digit) in digits.iter().rev().enumerate() {
        let shift = 3 * (14 - i);
        value = (value & !(7 << shift)) | (digit << shift);
    }
    CellIndex::try_from(value).map_err(|_| Error::Corrupt("Invalid pentagon address".into()))
}
/// Candidate keys, from the query to the block root.
#[must_use]
pub fn ancestors(cell: CellIndex) -> Vec<u16> {
    (3..=u8::from(cell.resolution()))
        .rev()
        .filter_map(|r| {
            let resolution = Resolution::try_from(r).ok()?;
            Some(address(cell.parent(resolution)?).1)
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn round_trip() {
        for r in 3..=8 {
            let c = h3o::LatLng::new(52.0, 4.0)
                .unwrap()
                .to_cell(Resolution::try_from(r).unwrap());
            let (b, k) = address(c);
            assert_eq!(cell_at(b, k).unwrap(), c);
            assert_eq!(ancestors(c).last(), Some(&0));
        }
        assert!(cell_at(41846, 0).is_err());
    }
}

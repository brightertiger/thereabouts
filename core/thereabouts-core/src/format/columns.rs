//! Bounded integer columns: frame-of-reference or local dictionary, then LZ4.
#![allow(clippy::indexing_slicing)] // Every row width and byte span is checked before indexed loops.
use super::container::{index, put, uint};
use crate::{Error, Result, error::ensure};
use std::collections::BTreeMap;
/// A decoded block never exceeds 64 KiB before integer unpacking.
pub const BLOCK_BYTES: usize = 65536;
/// Reserve more than LZ4's worst-case expansion so compressed blocks also fit 64 KiB.
pub const WRITER_BLOCK_BYTES: usize = BLOCK_BYTES - 512;
/// Four thousand rows amortize LZ4 and directory overhead without large miss reads.
pub const BLOCK_ROWS: usize = 4096;
/// Wide evidence schemas remain bounded independently of data cardinality.
pub const MAX_COLUMNS: usize = 64;

fn width(maximum: u64) -> usize {
    (64 - maximum.leading_zeros()) as usize
}
fn packed(values: &[u64], bits: usize) -> Vec<u8> {
    let mut bytes = vec![0; (values.len() * bits).div_ceil(8)];
    for (i, value) in values.iter().enumerate() {
        for bit in 0..bits {
            if value & (1_u64 << bit) != 0 {
                let at = i * bits + bit;
                bytes[at / 8] |= 1 << (at % 8);
            }
        }
    }
    bytes
}
fn unpack(bytes: &[u8], rows: usize, bits: usize) -> Result<Vec<u64>> {
    ensure(
        bits <= 64 && bytes.len() == (rows * bits).div_ceil(8),
        "Invalid packed column",
    )?;
    if !bytes.is_empty() && !(rows * bits).is_multiple_of(8) {
        ensure(
            bytes[bytes.len() - 1] >> ((rows * bits) % 8) == 0,
            "Nonzero packed padding",
        )?;
    }
    let mut values = vec![0; rows];
    for (i, value) in values.iter_mut().enumerate() {
        for bit in 0..bits {
            let at = i * bits + bit;
            *value |= u64::from((bytes[at / 8] >> (at % 8)) & 1) << bit;
        }
    }
    Ok(values)
}
/// Encode equal-width integer rows. The caller splits blocks exceeding `BLOCK_BYTES`.
pub fn encode(rows: &[Vec<u64>]) -> Result<Vec<u8>> {
    ensure(
        !rows.is_empty() && rows.len() <= BLOCK_ROWS,
        "Invalid column row count",
    )?;
    let columns = rows[0].len();
    ensure(
        columns > 0 && columns <= MAX_COLUMNS && rows.iter().all(|r| r.len() == columns),
        "Invalid column width",
    )?;
    let mut bytes = Vec::new();
    put(&mut bytes, rows.len() as u64, 4);
    put(&mut bytes, columns as u64, 4);
    for column in 0..columns {
        let values = rows.iter().map(|r| r[column]).collect::<Vec<_>>();
        let minimum = values.iter().copied().min().unwrap_or(0);
        let maximum = values.iter().copied().max().unwrap_or(0);
        let bits = width(maximum - minimum);
        let dictionary = values
            .iter()
            .map(|v| (*v, 0_u64))
            .collect::<BTreeMap<_, _>>();
        let dictionary = dictionary
            .into_keys()
            .enumerate()
            .map(|(i, v)| (v, i as u64))
            .collect::<BTreeMap<_, _>>();
        let dict_bits = width(dictionary.len().saturating_sub(1) as u64);
        let use_dict = dictionary.len() * 8 + (rows.len() * dict_bits).div_ceil(8)
            < (rows.len() * bits).div_ceil(8);
        let (mode, bits, base, count, values) = if use_dict {
            (
                1,
                dict_bits,
                0,
                dictionary.len(),
                values.iter().map(|v| dictionary[v]).collect::<Vec<_>>(),
            )
        } else {
            (
                0,
                bits,
                minimum,
                0,
                values.iter().map(|v| v - minimum).collect::<Vec<_>>(),
            )
        };
        put(&mut bytes, mode, 1);
        put(&mut bytes, bits as u64, 1);
        put(&mut bytes, count as u64, 2);
        put(&mut bytes, 0, 4);
        put(&mut bytes, base, 8);
        if use_dict {
            for value in dictionary.keys() {
                put(&mut bytes, *value, 8);
            }
        }
        bytes.extend(packed(&values, bits));
    }
    Ok(bytes)
}
/// Decode a checked uncompressed block; lengths are admitted before allocations.
#[allow(clippy::needless_range_loop)] // Wire order is column-major; the result is indexed by row and column.
pub fn decode(bytes: &[u8]) -> Result<Vec<Vec<u64>>> {
    ensure(bytes.len() <= BLOCK_BYTES, "Oversized column block")?;
    let rows = index(uint(bytes, 0, 4)?)?;
    let columns = index(uint(bytes, 4, 4)?)?;
    ensure(
        (1..=BLOCK_ROWS).contains(&rows) && (1..=MAX_COLUMNS).contains(&columns),
        "Invalid block shape",
    )?;
    let mut result = vec![vec![0; columns]; rows];
    let mut offset = 8;
    for column in 0..columns {
        let mode = uint(bytes, offset, 1)?;
        let bits = index(uint(bytes, offset + 1, 1)?)?;
        let count = index(uint(bytes, offset + 2, 2)?)?;
        let base = uint(bytes, offset + 8, 8)?;
        ensure(
            mode <= 1 && bits <= 64 && uint(bytes, offset + 4, 4)? == 0,
            "Invalid column descriptor",
        )?;
        ensure(
            (mode == 0 && count == 0) || (mode == 1 && (1..=rows).contains(&count) && base == 0),
            "Invalid column dictionary",
        )?;
        offset += 16;
        let mut dictionary = Vec::new();
        for _ in 0..count {
            dictionary.push(uint(bytes, offset, 8)?);
            offset += 8;
        }
        ensure(
            dictionary.windows(2).all(|w| w[0] < w[1]),
            "Unordered column dictionary",
        )?;
        let length = (rows * bits).div_ceil(8);
        let payload = bytes
            .get(offset..offset + length)
            .ok_or_else(|| Error::Corrupt("Truncated column".into()))?;
        for (row, value) in unpack(payload, rows, bits)?.into_iter().enumerate() {
            result[row][column] = if mode == 0 {
                base.checked_add(value)
                    .ok_or_else(|| Error::Corrupt("Column overflow".into()))?
            } else {
                *dictionary
                    .get(index(value)?)
                    .ok_or_else(|| Error::Corrupt("Dangling dictionary value".into()))?
            };
        }
        offset += length;
    }
    ensure(offset == bytes.len(), "Trailing column bytes")?;
    Ok(result)
}
/// Compress exactly one admitted block using the pure-Rust LZ4 block codec.
pub fn compress(bytes: &[u8]) -> Result<Vec<u8>> {
    ensure(bytes.len() <= BLOCK_BYTES, "Oversized uncompressed block")?;
    Ok(lz4_flex::block::compress(bytes))
}
/// Decompress into an admitted length; LZ4 does not allocate from embedded input sizes.
pub fn decompress(bytes: &[u8], length: usize) -> Result<Vec<u8>> {
    ensure(length <= BLOCK_BYTES, "Oversized decompressed block")?;
    lz4_flex::block::decompress(bytes, length)
        .map_err(|e| Error::Corrupt(format!("Invalid LZ4 block: {e}")))
}
#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;
    proptest! {
        #[test]
        fn round_trip(values in prop::collection::vec(any::<u64>(),1..200)) {
            let rows=values.into_iter().map(|v|vec![v,7,v%3]).collect::<Vec<_>>();
            let raw=encode(&rows).unwrap();
            let compressed=compress(&raw).unwrap();
            prop_assert_eq!(decode(&decompress(&compressed,raw.len()).unwrap()).unwrap(), rows);
            for length in [0,7,raw.len()/2,raw.len()-1] { prop_assert!(decode(&raw[..length]).is_err()); }
        }
    }
}

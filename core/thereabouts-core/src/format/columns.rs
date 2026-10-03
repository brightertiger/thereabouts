//! Bounded integer columns: scaled frames, local dictionaries and optional deltas.
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
pub(super) fn packed(values: &[u64], bits: usize) -> Vec<u8> {
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
pub(super) fn unpack(bytes: &[u8], rows: usize, bits: usize) -> Result<Vec<u64>> {
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
        let mut best = encode_column(&values, None, false);
        let mut size = lz4_flex::block::compress(&best).len();
        for skip_zero in [false, true] {
            if let Some((first, deltas)) = differences(&values, skip_zero) {
                let candidate = encode_column(&deltas, Some((first, skip_zero)), false);
                let compressed = lz4_flex::block::compress(&candidate).len();
                if compressed < size {
                    best = candidate;
                    size = compressed;
                }
            }
        }
        if values.iter().all(|v| u32::try_from(*v).is_ok()) {
            let signed = values.iter().map(|v| v ^ (1_u64 << 31)).collect::<Vec<_>>();
            let candidate = encode_column(&signed, None, true);
            if lz4_flex::block::compress(&candidate).len() < size {
                best = candidate;
            }
        }
        bytes.extend(best);
    }
    Ok(bytes)
}
fn differences(values: &[u64], skip_zero: bool) -> Option<(u64, Vec<u64>)> {
    let first = *values.iter().find(|v| !skip_zero || **v != 0)?;
    let mut previous = first;
    let mut deltas = Vec::with_capacity(values.len());
    for value in values {
        if skip_zero && *value == 0 {
            deltas.push(0);
        } else {
            let difference = value.wrapping_sub(previous);
            previous = *value;
            let delta = (difference << 1) ^ 0_u64.wrapping_sub(difference >> 63);
            deltas.push(if skip_zero {
                delta.checked_add(1)?
            } else {
                delta
            });
        }
    }
    Some((first, deltas))
}
fn gcd(mut a: u64, mut b: u64) -> u64 {
    while b != 0 {
        (a, b) = (b, a % b);
    }
    a
}
#[allow(clippy::cast_possible_truncation)] // Packed and aligned bit widths are at most 64.
fn encode_column(values: &[u64], first: Option<(u64, bool)>, signed: bool) -> Vec<u8> {
    let mut bytes = Vec::new();
    let minimum = values.iter().copied().min().unwrap_or(0);
    let maximum = values.iter().copied().max().unwrap_or(0);
    let divisor = values.iter().fold(0, |g, value| gcd(g, value - minimum));
    let divisor = if divisor > 1 && u32::try_from(divisor).is_ok() {
        divisor
    } else {
        1
    };
    let bits = width((maximum - minimum) / divisor);
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
    let use_dict = dictionary.len() * 8 + (values.len() * dict_bits).div_ceil(8)
        < (values.len() * bits).div_ceil(8);
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
            values
                .iter()
                .map(|v| (v - minimum) / divisor)
                .collect::<Vec<_>>(),
        )
    };
    put(
        &mut bytes,
        mode + if signed {
            6
        } else {
            first.map_or(0, |(_, skip)| if skip { 4 } else { 2 })
        },
        1,
    );
    put(&mut bytes, bits as u64, 1);
    put(&mut bytes, count as u64, 2);
    put(&mut bytes, if use_dict { 0 } else { divisor - 1 }, 4);
    put(&mut bytes, base, 8);
    if let Some((first, _)) = first {
        put(&mut bytes, first, 8);
    }
    if use_dict {
        for value in dictionary.keys() {
            put(&mut bytes, *value, 8);
        }
    }
    let mut aligned = bytes.clone();
    bytes.extend(packed(&values, bits));
    let byte_bits = bits.div_ceil(8) * 8;
    if byte_bits != bits {
        // Byte alignment can preserve repeated patterns that bit packing hides from LZ4.
        aligned[1] = byte_bits as u8;
        aligned.extend(packed(&values, byte_bits));
        if lz4_flex::block::compress(&aligned).len() < lz4_flex::block::compress(&bytes).len() {
            return aligned;
        }
    }
    bytes
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
        let divisor = uint(bytes, offset + 4, 4)? + 1;
        ensure(
            mode <= 7 && bits <= 64 && (mode % 2 == 0 || divisor == 1),
            "Invalid column descriptor",
        )?;
        ensure(
            (mode % 2 == 0 && count == 0)
                || (mode % 2 == 1 && (1..=rows).contains(&count) && base == 0),
            "Invalid column dictionary",
        )?;
        offset += 16;
        let mut previous = if (2..=5).contains(&mode) {
            let value = uint(bytes, offset, 8)?;
            offset += 8;
            value
        } else {
            0
        };
        let mut seen_nonzero = false;
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
            let value = if mode % 2 == 0 {
                value
                    .checked_mul(divisor)
                    .and_then(|value| base.checked_add(value))
                    .ok_or_else(|| Error::Corrupt("Column overflow".into()))?
            } else {
                *dictionary
                    .get(index(value)?)
                    .ok_or_else(|| Error::Corrupt("Dangling dictionary value".into()))?
            };
            result[row][column] = if mode >= 6 {
                ensure(
                    u32::try_from(value).is_ok(),
                    "Scaled signed value exceeds u32",
                )?;
                value ^ (1_u64 << 31)
            } else if mode >= 4 && value == 0 {
                0
            } else if mode >= 2 {
                let delta = if mode >= 4 { value - 1 } else { value };
                ensure(seen_nonzero || delta == 0, "Nonzero initial delta")?;
                seen_nonzero = true;
                let difference = (delta >> 1) ^ 0_u64.wrapping_sub(delta & 1);
                previous = previous.wrapping_add(difference);
                ensure(mode < 4 || previous != 0, "Noncanonical zero delta value")?;
                previous
            } else {
                value
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
    #[test]
    fn sequential_and_sparse_columns_use_differences() {
        for sparse in [false, true] {
            let rows = (0..2048_u64)
                .map(|i| {
                    vec![if sparse && i % 2 == 0 {
                        0
                    } else {
                        1_000_000 + i / 2
                    }]
                })
                .collect::<Vec<_>>();
            let encoded = encode(&rows).unwrap();
            assert!(uint(&encoded, 8, 1).unwrap() >= 2);
            assert_eq!(decode(&encoded).unwrap(), rows);
            let compressed = compress(&encoded).unwrap();
            assert!(compressed.len() < 200);
        }
    }
    #[test]
    fn signed_decimal_precision_is_lossless() {
        let rows = (-2000_i32..2000)
            .map(|i| vec![u64::from((i * 1000).cast_unsigned())])
            .collect::<Vec<_>>();
        let encoded = encode(&rows).unwrap();
        assert_eq!(decode(&encoded).unwrap(), rows);
        let mut forced = Vec::new();
        put(&mut forced, rows.len() as u64, 4);
        put(&mut forced, 1, 4);
        let values = rows
            .iter()
            .map(|r| r[0] ^ (1_u64 << 31))
            .collect::<Vec<_>>();
        forced.extend(encode_column(&values, None, true));
        assert_eq!(decode(&forced).unwrap(), rows);
        assert!(compress(&encoded).unwrap().len() < 6000);
    }
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

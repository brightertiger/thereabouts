//! Sorted front-coded UTF-8 with a permutation preserving stable pool IDs.
use super::{
    columns,
    container::{index, put, uint},
};
use crate::{Error, Result, error::ensure};

#[allow(clippy::cast_possible_truncation)] // Each emitted digit is explicitly masked to seven bits.
fn varint(bytes: &mut Vec<u8>, mut value: usize) {
    while value >= 128 {
        bytes.push((value as u8 & 127) | 128);
        value >>= 7;
    }
    bytes.push(value as u8);
}
fn read_varint(bytes: &[u8], offset: &mut usize) -> Result<usize> {
    let mut value = 0;
    for shift in (0..21).step_by(7) {
        let byte = *bytes
            .get(*offset)
            .ok_or_else(|| Error::Corrupt("Truncated string length".into()))?;
        *offset += 1;
        value |= usize::from(byte & 127) << shift;
        if byte < 128 {
            ensure(shift == 0 || byte != 0, "Noncanonical string length")?;
            return Ok(value);
        }
    }
    Err(Error::Corrupt("Oversized string length".into()))
}
pub(super) fn encode(values: &[String], reverse: bool, separate: bool) -> Result<Vec<u8>> {
    let transformed = values
        .iter()
        .map(|s| {
            let mut bytes = s.as_bytes().to_vec();
            if reverse {
                bytes.reverse();
            }
            bytes
        })
        .collect::<Vec<_>>();
    let mut order = transformed.iter().enumerate().collect::<Vec<_>>();
    order.sort_by(|a, b| a.1.cmp(b.1));
    let bits = values.len().saturating_sub(1).bit_width() as usize;
    let mut bytes = Vec::new();
    put(
        &mut bytes,
        u64::from(u32::MAX) - u64::from(reverse) - 2 * u64::from(separate),
        4,
    );
    put(&mut bytes, bits as u64, 4);
    bytes.extend(columns::packed(
        &order.iter().map(|(i, _)| *i as u64).collect::<Vec<_>>(),
        bits,
    ));
    let mut previous: &[u8] = &[];
    let mut prefixes = Vec::new();
    let mut lengths = Vec::new();
    let mut suffixes = Vec::new();
    for (_, text) in order {
        let text = text.as_slice();
        let common = previous
            .iter()
            .zip(text)
            .take_while(|(a, b)| a == b)
            .count();
        if separate {
            varint(&mut prefixes, common);
            varint(&mut lengths, text.len() - common);
        } else {
            varint(&mut suffixes, common);
            varint(&mut suffixes, text.len() - common);
        }
        suffixes.extend_from_slice(
            text.get(common..)
                .ok_or_else(|| Error::Corrupt("Invalid prefix length".into()))?,
        );
        previous = text;
    }
    bytes.extend(prefixes);
    bytes.extend(lengths);
    bytes.extend(suffixes);
    ensure(
        bytes.len() <= columns::BLOCK_BYTES,
        "Oversized front-coded block",
    )?;
    Ok(bytes)
}
pub(super) fn decode(bytes: &[u8], rows: usize) -> Result<Vec<String>> {
    let tag = u64::from(u32::MAX)
        .checked_sub(uint(bytes, 0, 4)?)
        .ok_or_else(|| Error::Corrupt("Invalid front-coded tag".into()))?;
    ensure(tag <= 3, "Invalid front-coded tag")?;
    let reverse = tag & 1 == 1;
    let separate = tag & 2 == 2;
    let bits = index(uint(bytes, 4, 4)?)?;
    ensure(
        bits == rows.saturating_sub(1).bit_width() as usize,
        "Invalid string permutation width",
    )?;
    let length = (rows * bits).div_ceil(8);
    let packed = bytes
        .get(8..8 + length)
        .ok_or_else(|| Error::Corrupt("Truncated string permutation".into()))?;
    let order = columns::unpack(packed, rows, bits)?;
    let mut values = vec![None; rows];
    let mut offset = 8 + length;
    let mut lengths = Vec::new();
    if separate {
        for _ in 0..rows {
            lengths.push((read_varint(bytes, &mut offset)?, 0));
        }
        for item in &mut lengths {
            item.1 = read_varint(bytes, &mut offset)?;
        }
    }
    let mut lengths = lengths.into_iter();
    let mut previous = Vec::<u8>::new();
    let mut total = (rows + 1) * 4;
    for ordinal in order {
        let (common, suffix) = if separate {
            lengths
                .next()
                .ok_or_else(|| Error::Corrupt("Missing string lengths".into()))?
        } else {
            (
                read_varint(bytes, &mut offset)?,
                read_varint(bytes, &mut offset)?,
            )
        };
        total += common + suffix;
        ensure(
            total <= columns::BLOCK_BYTES,
            "Expanded string block exceeds limit",
        )?;
        let mut text = previous
            .get(..common)
            .ok_or_else(|| Error::Corrupt("Invalid common prefix".into()))?
            .to_vec();
        text.extend_from_slice(
            bytes
                .get(offset..offset + suffix)
                .ok_or_else(|| Error::Corrupt("Truncated string suffix".into()))?,
        );
        offset += suffix;
        ensure(text >= previous, "Unsorted front-coded strings")?;
        previous.clone_from(&text);
        if reverse {
            text.reverse();
        }
        let text =
            String::from_utf8(text).map_err(|_| Error::Corrupt("Invalid pool UTF-8".into()))?;
        let slot = values
            .get_mut(index(ordinal)?)
            .ok_or_else(|| Error::Corrupt("Invalid pool permutation".into()))?;
        ensure(slot.is_none(), "Duplicate pool permutation entry")?;
        *slot = Some(text);
    }
    ensure(offset == bytes.len(), "Trailing string bytes")?;
    values
        .into_iter()
        .map(|s| s.ok_or_else(|| Error::Corrupt("Missing pool permutation entry".into())))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;
    proptest! {
        #[test]
        fn shuffled_unicode_round_trip(values in prop::collection::vec("[a-zA-Zé世\\n]{0,60}", 1..150)) {
            for reverse in [false, true] {
                for separate in [false, true] {
                    let bytes = encode(&values, reverse, separate).unwrap();
                    prop_assert_eq!(decode(&bytes, values.len()).unwrap(), values.clone());
                    for length in [0, 7, bytes.len()/2, bytes.len()-1] {
                        prop_assert!(decode(&bytes[..length], values.len()).is_err());
                    }
                }
            }
        }
        #[test]
        fn malformed_input_is_bounded(bytes in prop::collection::vec(any::<u8>(),0..1000), rows in 1usize..200) {
            let _ = decode(&bytes, rows);
        }
    }
    #[test]
    fn duplicate_permutation_is_rejected() {
        let mut bytes = encode(
            &["alpha".into(), "alpine".into(), "altitude".into()],
            false,
            true,
        )
        .unwrap();
        bytes[8] = 0;
        assert!(decode(&bytes, 3).is_err());
    }
}

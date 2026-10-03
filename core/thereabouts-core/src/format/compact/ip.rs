//! Binary search over version-specific starts; null locations preserve gaps.
use super::{Compact, first};
use crate::{
    Error, Result,
    error::ensure,
    format::{observation::Observation, table::Data},
};
use std::sync::Arc;
impl Compact {
    pub(crate) fn interval(
        &self,
        address: (u8, u128),
        evidence: bool,
        count: usize,
    ) -> Result<Vec<Arc<Observation>>> {
        let (version, address) = address;
        let table = self.table(if version == 4 { "starts4" } else { "starts6" })?;
        let Some((block, base)) = table.block_at_key(address)? else {
            return Ok(vec![]);
        };
        let Data::Integers(rows) = block.as_ref() else {
            return Err(Error::Corrupt("Invalid address table".into()));
        };
        let Some(local) = rows
            .partition_point(|r| start(r).is_ok_and(|s| s <= address))
            .checked_sub(1)
        else {
            return Ok(vec![]);
        };
        let row = rows
            .get(local)
            .ok_or_else(|| Error::Corrupt("Missing interval row".into()))?;
        let location = *row
            .get(2)
            .ok_or_else(|| Error::Corrupt("Missing interval location".into()))?;
        if location == 0 {
            return Ok(vec![]);
        }
        let ordinal = base + local;
        let role = if version == 4 {
            "evidence4"
        } else {
            "evidence6"
        };
        let mut record =
            self.record(location, ordinal as u64 + 1, role, ordinal, evidence, count)?;
        if evidence {
            let first = start(row)?;
            let last = if ordinal + 1 < table.rows {
                start(&table.row(ordinal + 1)?)?
                    .checked_sub(1)
                    .ok_or_else(|| Error::Corrupt("Reversed interval".into()))?
            } else if version == 4 {
                u128::from(u32::MAX)
            } else {
                u128::MAX
            };
            let render = |v: u128| {
                if version == 4 {
                    Ok(std::net::Ipv4Addr::from(
                        u32::try_from(v)
                            .map_err(|_| Error::Corrupt("Invalid IPv4 range".into()))?,
                    )
                    .to_string())
                } else {
                    Ok::<_, Error>(std::net::Ipv6Addr::from(v).to_string())
                }
            };
            record.text[3] = Some(format!("{}–{}", render(first)?, render(last)?));
            record.text[4] = Some(if version == 4 { "ipv4" } else { "ipv6" }.into());
        }
        Ok(vec![Arc::new(record)])
    }
}
pub(super) fn start(row: &[u64]) -> Result<u128> {
    ensure(row.len() == 3, "Invalid start row")?;
    Ok((u128::from(first(row)?) << 64)
        | u128::from(
            *row.get(1)
                .ok_or_else(|| Error::Corrupt("Missing address low bits".into()))?,
        ))
}

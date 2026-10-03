//! Whole-table integrity checks include cold evidence and unassigned address gaps.
use super::{Compact, ip::start};
use crate::{Error, Result, error::ensure};
use fst::Streamer;
impl Compact {
    fn verify_airport_spans(&self) -> Result<()> {
        let mut end = 0;
        let spans = self.table("airport_evidence")?;
        for row in 0..spans.rows {
            let span = spans.row(row)?;
            ensure(
                span.len() == 2 && span.first() == Some(&end),
                "Airport assertion span gap",
            )?;
            let count = span
                .get(1)
                .copied()
                .ok_or_else(|| Error::Corrupt("Missing assertion count".into()))?;
            end = end
                .checked_add(count)
                .ok_or_else(|| Error::Corrupt("Assertion count overflow".into()))?;
        }
        ensure(
            end == self.table("airport_assertions")?.rows as u64,
            "Unreferenced airport assertions",
        )
    }
    pub(crate) fn verify(&self, count: usize) -> Result<()> {
        for table in self.tables.values() {
            table.verify()?;
        }
        if self.family == "airports" {
            self.verify_airport_spans()?;
        }
        if let Some(keys) = &self.keys {
            let mut stream = keys.stream();
            while let Some((key, _)) = stream.next() {
                let key = std::str::from_utf8(key)
                    .map_err(|_| Error::Corrupt("Invalid key UTF-8".into()))?;
                self.lookup(key, true, count)?;
            }
        } else {
            let mut count_sources = 0;
            for (version, role) in [(4, "starts4"), (6, "starts6")] {
                let table = self.table(role)?;
                let mut previous = None;
                for row in 0..table.rows {
                    let values = table.row(row)?;
                    let address = start(&values)?;
                    ensure(
                        previous.is_none_or(|p| p < address)
                            && (version != 4 || address <= u128::from(u32::MAX)),
                        "Unsorted address starts",
                    )?;
                    if values.get(2) == Some(&0) {
                        let evidence = self
                            .table(if version == 4 {
                                "evidence4"
                            } else {
                                "evidence6"
                            })?
                            .row(row)?;
                        ensure(
                            evidence.len() == 6 && evidence.iter().all(|v| *v == 0),
                            "Gap has source evidence",
                        )?;
                    } else {
                        count_sources += 1;
                    }
                    self.interval((version, address), true, count)?;
                    previous = Some(address);
                }
            }
            ensure(
                count_sources == self.schema.source_rows,
                "IP source count disagrees",
            )?;
        }
        Ok(())
    }
}

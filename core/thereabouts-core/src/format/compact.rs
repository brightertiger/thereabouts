//! Format-2.1 forward tables: geography dictionaries, FST keys and cold evidence.
use super::{
    container::{Container, index},
    manifest::{self, Manifest},
    observation::Observation,
    table::{self, Table},
};
use crate::{Error, Result, error::ensure};
use fst::{IntoStreamer, Streamer};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, path::Path, sync::Arc};
mod ip;
mod record;
mod verify;

/// Family-specific evidence column names and source-row count are explicit metadata.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Schema {
    /// Details are reconstructed from dictionary-coded JSON scalar columns.
    pub detail_fields: Vec<String>,
    /// Source observations, counting one airport once rather than once per scheme.
    pub source_rows: u64,
}
/// Stable artifact roles; unknown forward tables are rejected by admission.
pub const ROLES: &[&str] = &[
    "records",
    "postings",
    "geographies",
    "locations",
    "details",
    "evidence",
    "airport_evidence",
    "airport_assertions",
    "evidence4",
    "evidence6",
    "starts4",
    "starts6",
    "strings",
    "evidence_strings",
];
/// Column schemas are shared by writer and reader, never inferred at lookup.
#[must_use]
pub fn detail_fields(family: &str) -> &'static [&'static str] {
    match family {
        "postal" => &[
            "admin1_name",
            "admin1_code",
            "admin2_name",
            "admin2_code",
            "admin3_name",
            "admin3_code",
            "accuracy",
            "variant",
        ],
        "airports" => &["type", "municipality", "region_code"],
        "locode" => &[
            "name_ascii",
            "subdivision_code",
            "function",
            "status",
            "iata_code",
            "date",
            "change",
            "remarks",
            "coordinates_raw",
        ],
        "phone" => &[
            "language",
            "description",
            "calling_code",
            "leading_digits",
            "national_prefix",
            "international_prefix",
            "link_status",
            "link_method",
        ],
        "ip" => &["city", "country_code", "region"],
        _ => &[],
    }
}
#[derive(Debug)]
pub(crate) struct Compact {
    family: String,
    schema: Schema,
    tables: BTreeMap<String, Table>,
    keys: Option<fst::Map<Vec<u8>>>,
}
impl Compact {
    pub(crate) fn open(root: &Path, manifest: &Manifest) -> Result<Self> {
        let schema = manifest
            .forward_columns
            .clone()
            .ok_or_else(|| Error::Corrupt("Missing forward column schema".into()))?;
        ensure(
            schema.detail_fields == detail_fields(&manifest.family),
            "Unsupported evidence schema",
        )?;
        let mut required = vec![
            "geographies",
            "locations",
            "strings",
            "evidence_strings",
            "details",
        ];
        if manifest.family == "ip" {
            required.extend(["starts4", "starts6", "evidence4", "evidence6"]);
        } else {
            required.extend(["records", "evidence"]);
        }
        if manifest.family == "airports" {
            required.extend(["postings", "airport_evidence", "airport_assertions"]);
        }
        ensure(
            required
                .iter()
                .all(|role| manifest.files.iter().any(|f| &f.kind == role)),
            "Missing compressed table inventory",
        )?;
        let mut tables = BTreeMap::new();
        for role in ROLES {
            let kind = if role.ends_with("strings") {
                table::STRING_KIND
            } else {
                table::INTEGER_KIND
            };
            tables.insert((*role).into(), Table::open(root, manifest, role, kind)?);
        }
        let keys = if manifest.family == "ip" {
            None
        } else {
            let files = manifest
                .files
                .iter()
                .filter(|f| f.kind == "keys")
                .collect::<Vec<_>>();
            ensure(files.len() == 1, "Expected one forward key FST")?;
            let file = files
                .first()
                .ok_or_else(|| Error::Corrupt("Missing key FST".into()))?;
            let c = Container::decode(
                std::fs::read(manifest::artifact_path(root, &file.path)?)?,
                11,
                &[1],
            )?;
            Some(
                std::panic::catch_unwind(|| super::fst::read(c.section(0).to_vec(), false))
                    .map_err(|_| Error::Corrupt("Malformed key FST".into()))??,
            )
        };
        let result = Self {
            family: manifest.family.clone(),
            schema,
            tables,
            keys,
        };
        for role in [
            "geographies",
            "locations",
            "strings",
            "evidence_strings",
            "details",
        ] {
            ensure(result.table(role)?.rows > 0, "Missing forward dictionary")?;
        }
        for (data, evidence) in if result.family == "ip" {
            vec![("starts4", "evidence4"), ("starts6", "evidence6")]
        } else {
            vec![("records", "evidence")]
        } {
            ensure(
                result.table(data)?.rows == result.table(evidence)?.rows,
                "Evidence alignment disagrees",
            )?;
        }
        if result.family != "ip" {
            ensure(
                result.schema.source_rows == result.table("records")?.rows as u64,
                "Source record count disagrees",
            )?;
        }
        if result.family == "airports" {
            ensure(
                result.table("airport_evidence")?.rows == result.table("postings")?.rows,
                "Airport evidence alignment disagrees",
            )?;
        }
        result.validate_keys()?;
        Ok(result)
    }
    fn table(&self, role: &str) -> Result<&Table> {
        self.tables
            .get(role)
            .ok_or_else(|| Error::Corrupt("Missing compact table".into()))
    }
    fn validate_keys(&self) -> Result<()> {
        if let Some(keys) = &self.keys {
            let role = if self.family == "airports" {
                "postings"
            } else {
                "records"
            };
            let rows = self.table(role)?.rows as u64;
            let mut stream = keys.stream();
            let mut previous = None;
            while let Some((key, value)) = stream.next() {
                ensure(
                    std::str::from_utf8(key).is_ok() && !key.is_empty(),
                    "Invalid forward key",
                )?;
                ensure(
                    value < rows && previous.map_or(value == 0, |p| p < value),
                    "Invalid key ordinal span",
                )?;
                previous = Some(value);
            }
            ensure(previous.is_some() == (rows > 0), "Unindexed source rows")?;
        }
        Ok(())
    }
    fn text(&self, reference: u64) -> Result<Option<String>> {
        if reference == 0 {
            return Ok(None);
        }
        self.table(if reference & 1 == 0 {
            "strings"
        } else {
            "evidence_strings"
        })?
        .string(index(reference >> 1)?)
        .map(Some)
    }
    fn span(&self, key: &str) -> Result<std::ops::Range<usize>> {
        let map = self
            .keys
            .as_ref()
            .ok_or_else(|| Error::Corrupt("Missing exact index".into()))?;
        let Some(first) = map.get(key) else {
            return Ok(0..0);
        };
        let mut next = map.range().gt(key).into_stream();
        let role = if self.family == "airports" {
            "postings"
        } else {
            "records"
        };
        let end = next
            .next()
            .map_or(self.table(role)?.rows as u64, |(_, v)| v);
        let (first, end) = (index(first)?, index(end)?);
        ensure(
            first < end && end <= self.table(role)?.rows,
            "Invalid key row span",
        )?;
        Ok(first..end)
    }
    pub(crate) fn lookup(
        &self,
        key: &str,
        evidence: bool,
        count: usize,
    ) -> Result<Vec<Arc<Observation>>> {
        let mut records = Vec::new();
        for posting in self.span(key)? {
            let row = if self.family == "airports" {
                index(first(&self.table("postings")?.row(posting)?)?)?
            } else {
                posting
            };
            let location = first(&self.table("records")?.row(row)?)?;
            let mut record =
                self.record(location, row as u64 + 1, "evidence", row, evidence, count)?;
            if evidence {
                match self.family.as_str() {
                    "postal" => record.text[3] = key.split_once('\0').map(|(_, code)| code.into()),
                    "locode" => {
                        record.text[3] = Some(key.into());
                        record.text[4] = Some("unlocode".into());
                    }
                    "phone" => record.text[3] = Some(key.into()),
                    "airports" => {
                        let fields = key.split('\0').collect::<Vec<_>>();
                        record.text[3] = fields.get(2).map(|s| (*s).into());
                        record.text[4] = fields.first().map(|s| (*s).into());
                    }
                    _ => {}
                }
            }
            if self.family == "airports" && evidence {
                let span = self.table("airport_evidence")?.row(posting)?;
                ensure(span.len() == 2, "Invalid airport evidence span")?;
                let first = index(first(&span)?)?;
                let length =
                    index(*span.get(1).ok_or_else(|| {
                        Error::Corrupt("Missing airport evidence length".into())
                    })?)?;
                let end = first
                    .checked_add(length)
                    .ok_or_else(|| Error::Corrupt("Airport span overflow".into()))?;
                ensure(
                    length > 0 && end <= self.table("airport_assertions")?.rows,
                    "Invalid airport evidence range",
                )?;
                for ordinal in first..end {
                    let alias = self.table("airport_assertions")?.row(ordinal)?;
                    ensure(alias.len() == 2, "Invalid airport assertion")?;
                    let mut variant = record.clone();
                    variant.text[2] = self.text(
                        *alias
                            .first()
                            .ok_or_else(|| Error::Corrupt("Missing airport name".into()))?,
                    )?;
                    variant.text[5] = self.details(
                        *alias
                            .get(1)
                            .ok_or_else(|| Error::Corrupt("Missing airport details".into()))?,
                    )?;
                    records.push(Arc::new(variant));
                }
            } else {
                records.push(Arc::new(record));
            }
        }
        Ok(records)
    }
    pub(crate) fn prefix(
        &self,
        key: &str,
        evidence: bool,
        count: usize,
    ) -> Result<Vec<Arc<Observation>>> {
        for length in (1..=key.len()).rev() {
            let prefix = key
                .get(..length)
                .ok_or_else(|| Error::Corrupt("Invalid prefix boundary".into()))?;
            if self.keys.as_ref().is_some_and(|m| m.contains_key(prefix)) {
                return self.lookup(prefix, evidence, count);
            }
        }
        Ok(vec![])
    }
}

fn first(row: &[u64]) -> Result<u64> {
    row.first()
        .copied()
        .ok_or_else(|| Error::Corrupt("Missing compact field".into()))
}

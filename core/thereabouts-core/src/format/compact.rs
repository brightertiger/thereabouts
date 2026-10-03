//! Format-2.1 forward tables: geography dictionaries, FST keys and cold evidence.
use super::{
    container::{Container, index},
    manifest::{self, Manifest},
    observation::Observation,
    table::{self, Data, Table},
};
use crate::{Error, Result, error::ensure};
use fst::{IntoStreamer, Streamer};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, path::Path, sync::Arc};
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
            required.push("postings");
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
        for row in self.span(key)? {
            let row = if self.family == "airports" {
                index(first(&self.table("postings")?.row(row)?)?)?
            } else {
                row
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
            records.push(Arc::new(record));
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
    #[allow(clippy::indexing_slicing)] // Tuple lengths are checked before every fixed-field access.
    fn record(
        &self,
        location: u64,
        identity: u64,
        role: &str,
        row: usize,
        evidence: bool,
        count: usize,
    ) -> Result<Observation> {
        let location = self.table("locations")?.row(index(location)?)?;
        ensure(location.len() == 4, "Invalid location tuple")?;
        let geo = self.table("geographies")?.row(index(first(&location)?)?)?;
        ensure(geo.len() == 3, "Invalid geographic tuple")?;
        let mut places = [0; 3];
        for (target, value) in places.iter_mut().zip(geo) {
            *target = u32::try_from(value)
                .map_err(|_| Error::Corrupt("Invalid geography reference".into()))?;
        }
        let mut record = Observation {
            identity: Some(identity),
            places,
            latitude: coordinate(&location, 1)?,
            longitude: coordinate(&location, 2)?,
            text: std::array::from_fn(|_| None),
        };
        if evidence {
            let fields = self.table(role)?.row(row)?;
            ensure(fields.len() == 6, "Invalid evidence tuple")?;
            record.text[0] = self.text(fields[0])?;
            record.text[1] = self.text(fields[1])?.map(|prefix| {
                if fields[2] == 0 {
                    prefix
                } else {
                    format!("{prefix}{}", fields[2] - 1)
                }
            });
            ensure(
                record
                    .text
                    .iter()
                    .take(2)
                    .all(|v| v.as_ref().is_some_and(|s| !s.is_empty())),
                "Missing source evidence identity",
            )?;
            record.text[2] = self.text(location[3])?;
            record.text[3] = self.text(fields[3])?;
            record.text[4] = self.text(fields[4])?;
            if fields[5] != 0 {
                let values = self.table("details")?.row(index(fields[5])?)?;
                ensure(
                    values.len() == self.schema.detail_fields.len(),
                    "Invalid details tuple",
                )?;
                let mut details = serde_json::Map::new();
                for (name, value) in self.schema.detail_fields.iter().zip(values) {
                    if let Some(text) = self.text(value)? {
                        details.insert(name.clone(), serde_json::from_str(&text)?);
                    }
                }
                record.text[5] = Some(serde_json::to_string(&details)?);
            }
        }
        record.validate(count)?;
        Ok(record)
    }
    pub(crate) fn verify(&self, count: usize) -> Result<()> {
        for table in self.tables.values() {
            table.verify()?;
        }
        if let Some(keys) = &self.keys {
            let mut stream = keys.stream();
            while let Some((key, _)) = stream.next() {
                let key = std::str::from_utf8(key)
                    .map_err(|_| Error::Corrupt("Invalid key UTF-8".into()))?;
                self.lookup(key, true, count)?;
            }
        } else {
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
                    self.interval((version, address), true, count)?;
                    previous = Some(address);
                }
            }
        }
        Ok(())
    }
}
fn first(row: &[u64]) -> Result<u64> {
    row.first()
        .copied()
        .ok_or_else(|| Error::Corrupt("Missing compact field".into()))
}
fn coordinate(row: &[u64], field: usize) -> Result<i32> {
    row.get(field)
        .copied()
        .and_then(|v| u32::try_from(v).ok())
        .map(u32::cast_signed)
        .ok_or_else(|| Error::Corrupt("Invalid coordinate field".into()))
}
fn start(row: &[u64]) -> Result<u128> {
    ensure(row.len() == 3, "Invalid start row")?;
    Ok((u128::from(first(row)?) << 64)
        | u128::from(
            *row.get(1)
                .ok_or_else(|| Error::Corrupt("Missing address low bits".into()))?,
        ))
}

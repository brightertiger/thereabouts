//! Plate query fields are admitted once; provenance pools stay cold until requested.
use super::{
    container::index,
    manifest::Manifest,
    plates::{Code, Prior, Rule, Tables},
    table::{self, Table},
};
use crate::{Error, Result, error::ensure};
use std::collections::BTreeMap;
pub(crate) const ROLES: &[&str] = &[
    "plate_formats",
    "plate_codes",
    "plate_priors",
    "plate_format_evidence",
    "plate_code_evidence",
    "strings",
    "evidence_strings",
];
#[derive(Debug)]
pub(crate) struct PlateColumns {
    tables: BTreeMap<String, Table>,
}
impl PlateColumns {
    pub(crate) fn open(root: &super::reader::Reader, manifest: &Manifest) -> Result<Self> {
        ensure(
            ROLES
                .iter()
                .all(|r| manifest.files.iter().any(|f| &f.kind == r)),
            "Missing plate columns",
        )?;
        let mut tables = BTreeMap::new();
        let cache = table::block_cache();
        for (identity, role) in ROLES.iter().enumerate() {
            tables.insert(
                (*role).into(),
                Table::open(
                    root,
                    manifest,
                    role,
                    if role.ends_with("strings") {
                        table::STRING_KIND
                    } else {
                        table::INTEGER_KIND
                    },
                    std::sync::Arc::clone(&cache),
                    identity,
                )?,
            );
        }
        let result = Self { tables };
        for (hot, cold) in [
            ("plate_formats", "plate_format_evidence"),
            ("plate_codes", "plate_code_evidence"),
        ] {
            ensure(
                result.table(hot)?.rows == result.table(cold)?.rows,
                "Plate evidence rows disagree",
            )?;
        }
        Ok(result)
    }
    fn table(&self, role: &str) -> Result<&Table> {
        self.tables
            .get(role)
            .ok_or_else(|| Error::Corrupt("Missing plate table".into()))
    }
    fn row(&self, role: &str, row: usize, width: usize) -> Result<Vec<u64>> {
        let row = self.table(role)?.row(row)?;
        ensure(row.len() == width, "Unexpected plate column count")?;
        Ok(row)
    }
    fn text(&self, reference: u64) -> Result<Option<String>> {
        if reference == 0 {
            return Ok(None);
        }
        Ok(Some(
            self.table(if reference.is_multiple_of(2) {
                "strings"
            } else {
                "evidence_strings"
            })?
            .string(index(reference / 2)?)?,
        ))
    }
    fn required(&self, reference: u64) -> Result<String> {
        self.text(reference)?
            .ok_or_else(|| Error::Corrupt("Missing plate text".into()))
    }
    fn hot(&self, reference: u64) -> Result<Option<String>> {
        ensure(
            reference.is_multiple_of(2),
            "Query field points into evidence",
        )?;
        self.text(reference)
    }
    fn hot_required(&self, reference: u64) -> Result<String> {
        self.hot(reference)?
            .ok_or_else(|| Error::Corrupt("Missing query field".into()))
    }
    #[allow(clippy::indexing_slicing)] // row checks the exact fixed schema width first.
    pub(crate) fn decode(&self, manifest: &Manifest) -> Result<Tables> {
        let schema = manifest
            .plate_columns
            .as_ref()
            .ok_or_else(|| Error::Corrupt("Missing plate policy".into()))?;
        let mut result = Tables {
            policy: schema.policy.clone(),
            formats: vec![],
            codes: vec![],
            priors: vec![],
            prior_available: schema.prior_available,
        };
        for i in 0..self.table("plate_formats")?.rows {
            let r = self.row("plate_formats", i, 9)?;
            result.formats.push(Rule {
                country_code: self.hot_required(r[0])?,
                series_id: self.hot_required(r[1])?,
                series_status: self.hot_required(r[2])?,
                pattern: self.hot_required(r[3])?,
                relaxed_pattern: self.hot_required(r[4])?,
                code_group: self.hot(r[5])?,
                scripts: serde_json::from_str(&self.hot_required(r[6])?)?,
                fixed_national_marks: serde_json::from_str(&self.hot_required(r[7])?)?,
                specificity_bits: f64::from_bits(r[8]),
            });
        }
        for i in 0..self.table("plate_codes")?.rows {
            let r = self.row("plate_codes", i, 10)?;
            result.codes.push(Code {
                country_code: self.hot_required(r[0])?,
                code: self.hot_required(r[1])?,
                name_en: self.hot(r[2])?,
                name_local: self.hot(r[3])?,
                unit_kind: self.hot_required(r[4])?,
                scope: self.hot_required(r[5])?,
                series_status: self.hot_required(r[6])?,
                subdivision_scope: self.hot(r[7])?,
                subdivision_codes: serde_json::from_str(&self.hot_required(r[8])?)?,
                source_key: r[9],
                evidence_row: i,
            });
        }
        for i in 0..self.table("plate_priors")?.rows {
            let r = self.row("plate_priors", i, 2)?;
            result.priors.push(Prior {
                country_code: self.hot_required(r[0])?,
                vehicles: r[1],
            });
        }
        ensure(
            schema.source_rows == (result.formats.len() + result.codes.len()) as u64,
            "Plate source count disagrees",
        )?;
        Ok(result)
    }
    pub(crate) fn provenance(&self, rule: usize) -> Result<String> {
        let row = self.row("plate_format_evidence", rule, 1)?;
        let text = self.required(
            *row.first()
                .ok_or_else(|| Error::Corrupt("Missing provenance".into()))?,
        )?;
        serde_json::from_str::<serde_json::Value>(&text)?;
        Ok(text)
    }
    pub(crate) fn source(&self, code: &Code) -> Result<(String, String)> {
        let row = self.row("plate_code_evidence", code.evidence_row, 2)?;
        ensure(
            row.first() == Some(&code.source_key),
            "Plate source identity disagrees",
        )?;
        Ok((
            self.required(code.source_key)?,
            self.required(
                *row.get(1)
                    .ok_or_else(|| Error::Corrupt("Missing license".into()))?,
            )?,
        ))
    }
    pub(crate) fn verify(&self, tables: &Tables) -> Result<()> {
        for table in self.tables.values() {
            table.verify()?;
        }
        for i in 0..tables.formats.len() {
            self.provenance(i)?;
        }
        for code in &tables.codes {
            self.source(code)?;
        }
        Ok(())
    }
}

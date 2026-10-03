//! Typed plate input adapter; no code-place or vehicle-prior defaults are guessed.
use crate::{Error, Result, error::ensure, source::Dataset};
use std::path::Path;
use thereabouts_core::format::{
    manifest::Manifest,
    plates::{Code, Policy, Prior, Rule, Tables},
};
// Plate evidence is small compared with spatial/IP data. Admission caps resident
// typed rows at 64 MiB, leaving space for JSON encoding well within the 2 GiB writer limit.
const PLATE_EVIDENCE_BYTES: usize = 64 * 1024 * 1024;
fn list(row: crate::arrow::Row<'_>, field: &str) -> Result<Vec<String>> {
    row.texts(field)
}
fn json(row: crate::arrow::Row<'_>, field: &str) -> Result<serde_json::Value> {
    Ok(serde_json::from_str(row.required(field)?)?)
}
pub(crate) fn emit(
    data: &Dataset,
    stage: &Path,
    manifest: &mut Manifest,
    allow_missing: &[String],
) -> Result<()> {
    let mut policy = None;
    for table in data.tables("plate_policy") {
        data.scan(table, |row| {
            ensure(policy.is_none(), "Repeated plate policy")?;
            policy = Some(serde_json::from_str::<Policy>(
                row.required("policy_json")?,
            )?);
            Ok(())
        })?;
    }
    let policy = policy.ok_or_else(|| Error::Input("Missing plate policy row".into()))?;
    let mut tables = Tables {
        policy,
        formats: vec![],
        codes: vec![],
        priors: vec![],
        prior_available: !allow_missing.iter().any(|s| s == "plate_priors"),
    };
    let mut bytes = 0;
    for table in data.tables("plate_formats") {
        data.scan(table, |row| {
            let rule = Rule {
                country_code: row.required("country_code")?.into(),
                series_id: row.required("series_id")?.into(),
                series_status: row.required("series_status")?.into(),
                pattern: row.required("pattern")?.into(),
                relaxed_pattern: row.required("relaxed_pattern")?.into(),
                code_group: row.text("code_group")?.map(str::to_owned),
                scripts: list(row, "scripts")?,
                fixed_national_marks: list(row, "fixed_national_marks")?,
                specificity_bits: row
                    .number("specificity_bits")?
                    .ok_or_else(|| Error::Input("Missing format specificity".into()))?,
                provenance: json(row, "provenance")?,
            };
            bytes += serde_json::to_vec(&rule)?.len();
            ensure(
                bytes <= PLATE_EVIDENCE_BYTES,
                "Plate evidence exceeds admission budget",
            )?;
            tables.formats.push(rule);
            Ok(())
        })?;
    }
    for table in data.tables("plate_codes") {
        data.scan(table, |row| {
            let code = Code {
                country_code: row.required("country_code")?.into(),
                code: row.required("code")?.into(),
                name_en: row.text("name_en")?.map(str::to_owned),
                name_local: row.text("name_local")?.map(str::to_owned),
                unit_kind: row.required("unit_kind")?.into(),
                scope: row.required("scope")?.into(),
                series_status: row.required("series_status")?.into(),
                subdivision_scope: row.text("subdivision_scope")?.map(str::to_owned),
                subdivision_codes: list(row, "subdivision_codes")?,
                source_url: row.required("source_url")?.into(),
                license: row.required("license")?.into(),
            };
            bytes += serde_json::to_vec(&code)?.len();
            ensure(
                bytes <= PLATE_EVIDENCE_BYTES,
                "Plate evidence exceeds admission budget",
            )?;
            tables.codes.push(code);
            Ok(())
        })?;
    }
    for table in data.tables("plate_priors") {
        data.scan(table, |row| {
            tables.priors.push(Prior {
                country_code: row.required("country_code")?.into(),
                vehicles: row
                    .unsigned("vehicles")?
                    .ok_or_else(|| Error::Input("Missing vehicle count".into()))?,
            });
            Ok(())
        })?;
    }
    let encoded = serde_json::to_vec(&tables)?;
    ensure(
        encoded.len() <= PLATE_EVIDENCE_BYTES,
        "Encoded plate evidence exceeds admission budget",
    )?;
    crate::add(
        stage,
        manifest,
        "plates.bin",
        "plates",
        &thereabouts_core::format::container::encode(7, &[(&encoded, 1)])?,
    )
}

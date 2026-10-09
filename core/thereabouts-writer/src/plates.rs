//! Typed plate input adapter; no code-place or vehicle-prior defaults are guessed.
use crate::{Error, Result, error::ensure, source::Dataset};
use std::path::Path;
use thereabouts_core::format::{
    manifest::Manifest,
    plates::{Code, Policy, Prior, Rule, Tables},
};
// Plate evidence is small compared with spatial/IP data. The 2026-10 world inputs
// need about 105 MiB of resident typed rows (143,971 code assertions; Wikidata query
// URLs average 523 bytes). Admission caps them at 256 MiB, half the 512 MiB
// working-set ceiling, leaving space for JSON encoding within the 2 GiB writer limit.
const PLATE_EVIDENCE_BYTES: usize = 256 * 1024 * 1024;
fn list(row: crate::arrow::Row<'_>, field: &str) -> Result<Vec<String>> {
    row.texts(field)
}
fn json(row: crate::arrow::Row<'_>, field: &str) -> Result<serde_json::Value> {
    Ok(serde_json::from_str(row.required(field)?)?)
}
pub(crate) fn emit(
    data: &Dataset,
    db: &rusqlite::Connection,
    stage: &Path,
    manifest: &mut Manifest,
    metadata: &mut thereabouts_core::format::metadata::Metadata,
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
    let mut rule_evidence = Vec::new();
    let mut code_evidence = Vec::new();
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
            };
            let provenance = json(row, "provenance")?.to_string();
            bytes += serde_json::to_vec(&rule)?.len() + provenance.len();
            rule_evidence.push(provenance);
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
                source_key: 0,
                evidence_row: code_evidence.len(),
            };
            let evidence = [
                row.required("source_url")?.to_owned(),
                row.required("license")?.to_owned(),
            ];
            bytes +=
                serde_json::to_vec(&code)?.len() + evidence.iter().map(String::len).sum::<usize>();
            code_evidence.push(evidence);
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
    // An empty table supplies no vehicle prior, exactly like an omitted one.
    tables.prior_available &= !tables.priors.is_empty();
    crate::plate_columns::emit(db, stage, manifest, &tables, &rule_evidence, &code_evidence)?;
    crate::compact_metadata::plate(metadata, &tables);
    Ok(())
}

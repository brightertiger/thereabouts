//! Pooled plate assertions; URLs, licenses and provenance occupy cold sections.
use crate::{Result, compact::Rows, dictionaries::Dictionaries};
use rusqlite::Connection;
use std::path::Path;
use thereabouts_core::format::{
    manifest::Manifest,
    plates::{Schema, Tables},
};
pub(crate) fn emit(
    db: &Connection,
    stage: &Path,
    manifest: &mut Manifest,
    tables: &Tables,
    rule_evidence: &[String],
    code_evidence: &[[String; 2]],
) -> Result<()> {
    let dict = Dictionaries::new(db)?;
    manifest.format_minor = 2;
    manifest.plate_columns = Some(Schema {
        policy: tables.policy.clone(),
        prior_available: tables.prior_available,
        source_rows: (tables.formats.len() + tables.codes.len()) as u64,
    });
    let mut formats = Rows::new(stage, "plate_formats");
    let mut evidence = Rows::new(stage, "plate_format_evidence");
    for (i, (r, provenance)) in tables.formats.iter().zip(rule_evidence).enumerate() {
        let mut row = Vec::new();
        for value in [
            Some(r.country_code.as_str()),
            Some(&r.series_id),
            Some(&r.series_status),
            Some(&r.pattern),
            Some(&r.relaxed_pattern),
            r.code_group.as_deref(),
            Some(&serde_json::to_string(&r.scripts)?),
            Some(&serde_json::to_string(&r.fixed_national_marks)?),
        ] {
            row.push(dict.string(value, false)?);
        }
        row.push(r.specificity_bits.to_bits());
        formats.push(manifest, i as u128, row)?;
        evidence.push(
            manifest,
            i as u128,
            vec![dict.string(Some(provenance), true)?],
        )?;
    }
    formats.finish(manifest)?;
    evidence.finish(manifest)?;
    let mut codes = Rows::new(stage, "plate_codes");
    let mut evidence = Rows::new(stage, "plate_code_evidence");
    for (i, (c, source)) in tables.codes.iter().zip(code_evidence).enumerate() {
        let mut row = Vec::new();
        for value in [
            Some(c.country_code.as_str()),
            Some(&c.code),
            c.name_en.as_deref(),
            c.name_local.as_deref(),
            Some(&c.unit_kind),
            Some(&c.scope),
            Some(&c.series_status),
            c.subdivision_scope.as_deref(),
            Some(&serde_json::to_string(&c.subdivision_codes)?),
        ] {
            row.push(dict.string(value, false)?);
        }
        let url = dict.string(source.first().map(String::as_str), true)?;
        row.push(url);
        codes.push(manifest, i as u128, row)?;
        evidence.push(
            manifest,
            i as u128,
            vec![url, dict.string(source.get(1).map(String::as_str), true)?],
        )?;
    }
    codes.finish(manifest)?;
    evidence.finish(manifest)?;
    let mut priors = Rows::new(stage, "plate_priors");
    for (i, p) in tables.priors.iter().enumerate() {
        priors.push(
            manifest,
            i as u128,
            vec![dict.string(Some(&p.country_code), false)?, p.vehicles],
        )?;
    }
    priors.finish(manifest)?;
    dict.emit(stage, manifest, 0)
}

//! Typed plate evidence, independent of Python's reference implementation.
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
/// One published syntax assertion; source metadata remains attached.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Rule {
    /// ISO country or territory.
    pub country_code: String,
    /// Exact source series identifier.
    pub series_id: String,
    /// Published current/historic/unknown status.
    pub series_status: String,
    /// Full-match regular expression.
    pub pattern: String,
    /// Relaxation only at source-declared separator positions.
    pub relaxed_pattern: String,
    /// Named geographic capture, if encoded.
    pub code_group: Option<String>,
    /// Explicit metadata for script rarity.
    pub scripts: Vec<String>,
    /// Literal national marks within the serial.
    pub fixed_national_marks: Vec<String>,
    /// Exported information heuristic; never recalculated by the reader.
    pub specificity_bits: f64,
    /// Published provenance, including source identifiers or URLs.
    pub provenance: serde_json::Value,
}
/// One code-to-registration-unit assertion; never treated as a canonical city.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Code {
    /// ISO country or territory.
    pub country_code: String,
    /// Native code spelling, preserving leading zeros.
    pub code: String,
    /// Published English label.
    pub name_en: Option<String>,
    /// Published local label.
    pub name_local: Option<String>,
    /// Policy-mapped geographic level.
    pub unit_kind: String,
    /// Registration unit versus entity association.
    pub scope: String,
    /// Published temporal status.
    pub series_status: String,
    /// Narrower context required by the assertion.
    pub subdivision_scope: Option<String>,
    /// Explicit ISO subdivision identifiers; no name-based joins.
    pub subdivision_codes: Vec<String>,
    /// Source URL, retained in evidence.
    pub source_url: String,
    /// Per-assertion license.
    pub license: String,
}
/// Published vehicle stock counts; missing countries use their median under the policy.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Prior {
    /// ISO country code.
    pub country_code: String,
    /// Published road motor vehicle count.
    pub vehicles: u64,
}
/// Declarative geography restrictions.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Geography {
    /// Countries whose serials require an unsupported subnational hint.
    pub excluded_countries: Vec<String>,
    /// Explicit country-specific parent-prefix lengths.
    pub state_prefix: BTreeMap<String, usize>,
    /// Whether unknown temporal status can establish geography.
    pub unknown_status_eligible: bool,
    /// Non-geographic matches block finer claims.
    pub block_if_non_geographic_format_matches: bool,
    /// Historic geography needs an explicit series.
    pub historic_requires_explicit_series: bool,
    /// Scopes eligible for geography.
    pub allowed_scopes: Vec<String>,
}
/// A frozen normalization and ranking policy, including Unicode decimal mappings.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Policy {
    /// Maximum Unicode scalar count for inference.
    pub max_input_length: usize,
    /// Characters removed only for captured-code equality.
    pub code_separators: String,
    /// Source unit kind to place/state mapping.
    pub levels: BTreeMap<String, String>,
    /// Explicit script regular expressions.
    pub script_patterns: BTreeMap<String, String>,
    /// Known-code, mark, script, specificity, prior and relaxation weights.
    pub weights: BTreeMap<String, f64>,
    /// Geographic exclusions and eligibility.
    pub geography: Geography,
    /// Unicode decimal zero code points; each starts ten consecutive decimal digits.
    pub decimal_zeroes: Vec<u32>,
    /// Unicode database version used by the code equality mapping.
    pub decimal_unicode_version: String,
}
/// Plate evidence in a kind-seven JSON section; admission is bounded by the writer.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Tables {
    /// Matching and geography policy.
    pub policy: Policy,
    /// Source format rules in source order.
    pub formats: Vec<Rule>,
    /// Source code assertions in source order.
    pub codes: Vec<Code>,
    /// Observed vehicle counts, empty only in an explicitly incomplete sample.
    pub priors: Vec<Prior>,
    /// Explicitly records whether vehicle-prior evidence was supplied.
    pub prior_available: bool,
}

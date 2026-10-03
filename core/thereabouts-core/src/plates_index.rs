//! Compile plate patterns once and retain explicit country/code and ranking indexes.
use crate::{
    Error, Result,
    error::ensure,
    format::plates::{Code, Rule, Tables},
};
use regex::Regex;
use std::collections::{BTreeMap, BTreeSet};
use unicode_normalization::UnicodeNormalization;
/// Normalize NFC, ASCII case and the exact Python whitespace set from the plate contract.
pub(crate) fn normalize(value: &str) -> String {
    value
        .nfc()
        .map(|c| c.to_ascii_uppercase())
        .collect::<String>()
        .split(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
#[derive(Debug)]
pub(crate) struct Compiled {
    pub(crate) rule: Rule,
    exact: Regex,
    relaxed: Regex,
}
#[derive(Debug)]
pub(crate) struct PlateIndex {
    pub(crate) tables: Tables,
    rules: Vec<Compiled>,
    codes: BTreeMap<(String, String), Vec<usize>>,
    scripts: Vec<(String, Regex, f64)>,
    priors: BTreeMap<String, u64>,
    median: f64,
}
#[derive(Clone, Debug)]
pub(crate) struct Hit {
    pub(crate) rule: usize,
    pub(crate) code: Option<String>,
    pub(crate) score: f64,
    pub(crate) relaxed: bool,
}
impl PlateIndex {
    pub(crate) fn new(tables: Tables, country_count: usize) -> Result<Self> {
        ensure(
            tables.policy.max_input_length == 64,
            "Unsupported plate input limit",
        )?;
        ensure(
            tables.prior_available != tables.priors.is_empty(),
            "Plate prior availability disagrees",
        )?;
        for name in [
            "known_code",
            "fixed_mark",
            "script",
            "specificity",
            "log_vehicle_prior",
            "relaxed_penalty",
        ] {
            ensure(
                tables
                    .policy
                    .weights
                    .get(name)
                    .is_some_and(|v| v.is_finite()),
                "Missing plate scoring weight",
            )?;
        }
        let mut rules = Vec::new();
        let compile = |pattern: &str| {
            Regex::new(&format!("\\A(?:{pattern})\\z"))
                .map_err(|e| Error::Corrupt(format!("Invalid plate regex: {e}")))
        };
        for rule in &tables.formats {
            ensure(
                rule.specificity_bits.is_finite(),
                "Nonfinite plate specificity",
            )?;
            let exact = compile(&rule.pattern)?;
            let relaxed = compile(&rule.relaxed_pattern)?;
            if let Some(group) = &rule.code_group {
                ensure(
                    exact.capture_names().any(|n| n == Some(group))
                        && relaxed.capture_names().any(|n| n == Some(group)),
                    "Missing plate capture",
                )?;
            }
            rules.push(Compiled {
                rule: rule.clone(),
                exact,
                relaxed,
            });
        }
        let mut scripts = Vec::new();
        for (name, pattern) in &tables.policy.script_patterns {
            let countries = tables
                .formats
                .iter()
                .filter(|r| r.scripts.contains(name))
                .map(|r| &r.country_code)
                .collect::<BTreeSet<_>>()
                .len()
                .max(1);
            let regex = Regex::new(pattern)
                .map_err(|e| Error::Corrupt(format!("Invalid script regex: {e}")))?;
            scripts.push((name.clone(), regex, ratio_log(country_count, countries)));
        }
        let priors = tables
            .priors
            .iter()
            .map(|p| (p.country_code.clone(), p.vehicles))
            .collect::<BTreeMap<_, _>>();
        ensure(
            priors.len() == tables.priors.len(),
            "Repeated vehicle prior",
        )?;
        let mut counts = priors.values().copied().collect::<Vec<_>>();
        counts.sort_unstable();
        let median = median(&counts);
        let mut index = Self {
            tables,
            rules,
            codes: BTreeMap::new(),
            scripts,
            priors,
            median,
        };
        for (i, row) in index.tables.codes.iter().enumerate() {
            index
                .codes
                .entry((row.country_code.clone(), index.code_key(&row.code)))
                .or_default()
                .push(i);
        }
        Ok(index)
    }
    pub(crate) fn code_key(&self, value: &str) -> String {
        normalize(value)
            .chars()
            .filter(|c| !self.tables.policy.code_separators.contains(*c))
            .map(|c| {
                self.tables
                    .policy
                    .decimal_zeroes
                    .iter()
                    .find_map(|zero| {
                        u32::from(c)
                            .checked_sub(*zero)
                            .filter(|d| *d < 10)
                            .and_then(|d| char::from_digit(d, 10))
                    })
                    .unwrap_or(c)
            })
            .collect()
    }
    pub(crate) fn known(&self, country: &str, code: &str) -> Vec<&Code> {
        self.codes
            .get(&(country.into(), self.code_key(code)))
            .into_iter()
            .flatten()
            .filter_map(|i| self.tables.codes.get(*i))
            .collect()
    }
    pub(crate) fn rule(&self, hit: &Hit) -> Result<&Rule> {
        self.rules
            .get(hit.rule)
            .map(|c| &c.rule)
            .ok_or_else(|| Error::Corrupt("Missing plate rule".into()))
    }
    pub(crate) fn matches(
        &self,
        value: &str,
        country: Option<&str>,
        series: Option<&str>,
    ) -> Result<Vec<Hit>> {
        let mut hits = Vec::new();
        let mut seen = BTreeSet::new();
        let rarity = self
            .scripts
            .iter()
            .filter(|(name, re, _)| {
                !matches!(name.as_str(), "Latin" | "ASCII digits") && re.is_match(value)
            })
            .map(|(_, _, r)| *r)
            .fold(0.0_f64, f64::max);
        let weight = |name| {
            self.tables
                .policy
                .weights
                .get(name)
                .copied()
                .ok_or_else(|| Error::Corrupt("Missing plate weight".into()))
        };
        for (i, compiled) in self.rules.iter().enumerate() {
            let rule = &compiled.rule;
            if country.is_some_and(|c| c != rule.country_code)
                || series.is_some_and(|s| s != rule.series_id)
            {
                continue;
            }
            let (captures, relaxed) = if let Some(c) = compiled.exact.captures(value) {
                (c, false)
            } else if let Some(c) = compiled.relaxed.captures(value) {
                (c, true)
            } else {
                continue;
            };
            let code = rule
                .code_group
                .as_ref()
                .and_then(|g| captures.name(g))
                .map(|m| m.as_str().to_owned());
            if !seen.insert((
                &rule.country_code,
                &rule.series_status,
                if relaxed {
                    &rule.relaxed_pattern
                } else {
                    &rule.pattern
                },
                code.clone(),
            )) {
                continue;
            }
            let known = code
                .as_ref()
                .is_some_and(|c| !self.known(&rule.country_code, c).is_empty());
            let fixed = rule
                .fixed_national_marks
                .iter()
                .any(|m| !m.is_empty() && value.contains(m));
            let prior = if self.tables.prior_available {
                weight("log_vehicle_prior")?
                    * count_float(self.priors.get(&rule.country_code).copied(), self.median)
                        .max(1.0)
                        .log2()
            } else {
                0.0
            };
            let score = weight("known_code")? * f64::from(known)
                + weight("fixed_mark")? * f64::from(fixed)
                + weight("script")? * rarity
                + weight("specificity")? * rule.specificity_bits
                + prior
                - if relaxed {
                    weight("relaxed_penalty")?
                } else {
                    0.0
                };
            hits.push(Hit {
                rule: i,
                code,
                score: (score * 1e6).round_ties_even() / 1e6,
                relaxed,
            });
        }
        Ok(hits)
    }
}
#[allow(clippy::cast_precision_loss)] // Scores are heuristic f64 values by the published policy.
fn count_float(value: Option<u64>, fallback: f64) -> f64 {
    value.map_or(fallback, |n| n as f64)
}
#[allow(clippy::cast_precision_loss)]
fn ratio_log(a: usize, b: usize) -> f64 {
    (a.max(1) as f64 / b as f64).log2()
}
fn median(values: &[u64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let right = count_float(values.get(values.len() / 2).copied(), 0.0);
    if values.len().is_multiple_of(2) {
        right.midpoint(count_float(values.get(values.len() / 2 - 1).copied(), 0.0))
    } else {
        right
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;
    #[test]
    fn plate_normalization_preserves_scripts_and_uses_python_whitespace() {
        assert_eq!(normalize("  mh\u{a0}12\u{1c}ab 1234 "), "MH 12 AB 1234");
        assert_eq!(normalize("e\u{301} а A"), "é а A");
        assert_ne!(normalize("А"), normalize("A"));
    }
    proptest! {
        #[test]
        fn normalization_is_idempotent(value in "[a-zA-Z0-9 -]{0,100}") {
            let once=normalize(&value);
            prop_assert_eq!(normalize(&once),once);
        }
    }
}

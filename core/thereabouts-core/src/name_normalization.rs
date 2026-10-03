//! Pack-carried name normalization, shared by writer and every lookup binding.
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use unicode_casefold::UnicodeCaseFold;
use unicode_normalization::{UnicodeNormalization, char::is_combining_mark};
/// Normalization steps and abbreviations are explicit release data.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Policy {
    /// Ordered supported algorithm names.
    pub steps: Vec<String>,
    /// Full Unicode case-fold table version.
    pub casefold_unicode: String,
    /// Unicode decomposition/composition table version.
    pub normalization_unicode: String,
    /// Whole-token expansions, applied after punctuation/space normalization.
    pub expansions: BTreeMap<String, String>,
}
impl Default for Policy {
    fn default() -> Self {
        let c = unicode_casefold::UNICODE_VERSION;
        let n = unicode_normalization::UNICODE_VERSION;
        Self {
            steps: [
                "nfkc",
                "casefold_full_non_turkic",
                "fold_latin_cyrillic_greek",
                "collapse_punctuation_whitespace",
                "expand_tokens",
            ]
            .map(str::to_owned)
            .to_vec(),
            casefold_unicode: format!("{}.{}.{}", c.0, c.1, c.2),
            normalization_unicode: format!("{}.{}.{}", n.0, n.1, n.2),
            expansions: BTreeMap::from([
                ("st".into(), "saint".into()),
                ("ste".into(), "sainte".into()),
            ]),
        }
    }
}
impl Policy {
    /// Reject unsupported Unicode tables or algorithm changes instead of guessing.
    pub fn validate(&self) -> crate::Result<()> {
        let supported = Self::default();
        if self.steps != supported.steps
            || self.casefold_unicode != supported.casefold_unicode
            || self.normalization_unicode != supported.normalization_unicode
        {
            return Err(crate::Error::Incompatible(
                "Unsupported name normalization".into(),
            ));
        }
        crate::error::ensure(
            self.expansions.iter().all(|(k, v)| {
                !k.is_empty()
                    && !v.is_empty()
                    && k.chars().chain(v.chars()).all(|c| c.is_ascii_lowercase())
            }),
            "Invalid name expansion",
        )
    }
}
/// Apply the pack's policy without transliterating or removing CJK marks.
#[must_use]
pub fn normalize(value: &str, policy: &Policy) -> String {
    let folded = value.nfkc().case_fold().collect::<String>();
    let mut text = String::new();
    let mut strip = false;
    for c in folded.nfd() {
        if is_combining_mark(c) {
            if !strip {
                text.push(c);
            }
        } else if c.is_alphanumeric() {
            strip = matches!(u32::from(c),0x0041..=0x024f|0x0370..=0x052f|0x1c80..=0x1c8f|0x1d00..=0x1fff|0x2c60..=0x2c7f|0xa640..=0xa69f|0xa720..=0xa7ff|0xab30..=0xab6f);
            text.push(c);
        } else {
            strip = false;
            text.push(' ');
        }
    }
    text.nfc()
        .collect::<String>()
        .split_whitespace()
        .map(|word| policy.expansions.get(word).map_or(word, String::as_str))
        .collect::<Vec<_>>()
        .join(" ")
}
/// Unique Unicode-scalar trigrams with explicit start/end boundaries.
#[must_use]
pub fn trigrams(value: &str) -> BTreeSet<String> {
    let chars = format!("^{value}$").chars().collect::<Vec<_>>();
    chars.windows(3).map(|w| w.iter().collect()).collect()
}
/// Bounded edit distance is evaluated only for trigram candidates.
#[must_use]
#[allow(clippy::indexing_slicing)] // Row width is b.len()+1; loops are bounded by that width.
pub fn close(a: &str, b: &str) -> bool {
    let a = a.chars().collect::<Vec<_>>();
    let b = b.chars().collect::<Vec<_>>();
    let threshold = (a.len() / 4).clamp(1, 3);
    if a.len().abs_diff(b.len()) > threshold {
        return false;
    }
    let mut previous = (0..=b.len()).collect::<Vec<_>>();
    let mut row = vec![0; b.len() + 1];
    for (i, left) in a.iter().enumerate() {
        row[0] = i + 1;
        for (j, right) in b.iter().enumerate() {
            row[j + 1] = (previous[j + 1] + 1)
                .min(row[j] + 1)
                .min(previous[j] + usize::from(left != right));
        }
        if row.iter().all(|cost| *cost > threshold) {
            return false;
        }
        std::mem::swap(&mut previous, &mut row);
    }
    previous[b.len()] <= threshold
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn scripts_casefold_and_expansions() {
        let p = Policy::default();
        assert_eq!(normalize("Ｓt. Étienne", &p), "saint etienne");
        assert_eq!(normalize("Straße", &p), "strasse");
        assert_eq!(normalize("МОСКВА ΆΘΉΝΑ", &p), "москва αθηνα");
        assert_eq!(normalize("東京 ガ", &p), "東京 ガ");
        assert!(close("sprngfield", "springfield"));
        assert!(!close("paris", "springfield"));
    }
}

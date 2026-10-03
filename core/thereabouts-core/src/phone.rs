//! E.164 syntax and longest published prefix; no inference from free-form descriptions.
use crate::{
    Result,
    format::Pack,
    result::{Kind, LookupResult, Status},
};
/// Normalize international E.164 input; spaces, parentheses and hyphens are presentation.
#[must_use]
pub fn normalize(value: &str) -> Option<String> {
    let value = value
        .trim_matches(|c: char| c.is_ascii_whitespace())
        .strip_prefix('+')?;
    let mut digits = String::new();
    for c in value.chars() {
        if c.is_ascii_digit() {
            digits.push(c);
        } else if !matches!(c, ' ' | '-' | '(' | ')') {
            return None;
        }
    }
    crate::format::trie::valid_prefix(&digits).then_some(digits)
}
impl Pack {
    /// Match the longest stored E.164 prefix; unresolved shared codes return countries as candidates.
    pub fn phone(&self, value: &str, evidence: bool) -> Result<LookupResult> {
        self.require_family("phone")?;
        let Some(digits) = normalize(value) else {
            let mut result = LookupResult::empty(Status::InvalidInput);
            result.kind = Kind::PhonePrefix;
            result.hint =
                Some("Use phone(\"+91 22 1234 5678\") with an international calling code.".into());
            return Ok(result);
        };
        self.forward_result(
            self.prefix_observations(&digits, evidence)?,
            Kind::PhonePrefix,
            evidence,
        )
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn e164_syntax() {
        assert_eq!(
            super::normalize("+1 (202) 555-0123").as_deref(),
            Some("12025550123")
        );
        for bad in [
            "1202",
            "+0123",
            "+1234567890123456",
            "++12",
            "+1 x202",
            "+１２",
        ] {
            assert!(super::normalize(bad).is_none());
        }
    }
}

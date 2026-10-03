//! Postal codes require explicit country context and preserve leading zeroes.
use crate::{
    Result,
    format::Pack,
    forward::{country, normalize_code},
    result::{Kind, LookupResult, Status},
};
impl Pack {
    /// Resolve a published postal association; missing country is an invalid query.
    pub fn postal(&self, value: &str, hint: Option<&str>, evidence: bool) -> Result<LookupResult> {
        self.require_family("postal")?;
        let invalid = || {
            let mut result = LookupResult::empty(Status::InvalidInput);
            result.kind = Kind::Postal;
            result.hint = Some("Use postal(code, country=\"XX\"); preserve leading zeros.".into());
            result
        };
        let Some(country) = hint.and_then(country) else {
            return Ok(invalid());
        };
        let Some(code) = normalize_code(value, &self.manifest.normalization) else {
            return Ok(invalid());
        };
        self.forward_result(
            self.observations(&format!("{country}\0{code}"))?,
            Kind::Postal,
            evidence,
        )
    }
}

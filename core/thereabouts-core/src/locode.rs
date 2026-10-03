//! UN/LOCODE is a country prefix followed by a three-character location code.
use crate::{
    Result,
    format::Pack,
    forward::{country, normalize_code},
    result::{Kind, LookupResult, Status},
};
impl Pack {
    /// Resolve a full LOCODE or a three-character location with an explicit country.
    pub fn locode(&self, value: &str, hint: Option<&str>, evidence: bool) -> Result<LookupResult> {
        self.require_family("locode")?;
        let invalid = || {
            let mut result = LookupResult::empty(Status::InvalidInput);
            result.kind = Kind::TradeLocation;
            result.hint = Some("Use locode(\"INBOM\") or locode(\"BOM\", country=\"IN\").".into());
            result
        };
        let Some(mut code) = normalize_code(value, &self.manifest.normalization) else {
            return Ok(invalid());
        };
        let country = hint.and_then(country);
        if hint.is_some() && country.is_none() {
            return Ok(invalid());
        }
        if code.len() == 3 {
            let Some(country) = &country else {
                return Ok(invalid());
            };
            code.insert_str(0, country);
        }
        if !valid(&code) || country.is_some_and(|c| !code.starts_with(&c)) {
            return Ok(invalid());
        }
        self.forward_result(
            self.observations(&code, evidence)?,
            Kind::TradeLocation,
            evidence,
        )
    }
}
/// Admit the published UN/LOCODE alphabet, including digits in location codes.
#[must_use]
pub fn valid(code: &str) -> bool {
    code.len() == 5
        && code.bytes().take(2).all(|c| c.is_ascii_uppercase())
        && code
            .bytes()
            .skip(2)
            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit())
}
#[cfg(test)]
mod tests {
    #[test]
    fn locode_alphabet() {
        assert!(super::valid("INBOM"));
        assert!(super::valid("US3CX"));
        for bad in ["BOM", "1NBOM", "İNBO", "IN-BO", "inbom"] {
            assert!(!super::valid(bad));
        }
    }
}

//! Airport schemes retain their own namespaces; automatic lookup searches IATA and ICAO.
use crate::{
    Result,
    format::Pack,
    forward::{country, normalize_code},
    result::{Kind, LookupResult, Status},
};
/// Schemes supported by published airport observations.
pub const SCHEMES: [&str; 5] = ["iata", "icao", "gps", "local", "ident"];
impl Pack {
    /// Resolve a code in an explicit scheme, or combine IATA and ICAO candidates.
    pub fn airport(
        &self,
        value: &str,
        scheme: Option<&str>,
        hint: Option<&str>,
        evidence: bool,
    ) -> Result<LookupResult> {
        self.require_family("airports")?;
        let invalid = || {
            let mut result = LookupResult::empty(Status::InvalidInput);
            result.kind = Kind::Airport;
            result.hint = Some("Use airport(code, scheme=\"iata|icao|gps|local|ident\"); local codes require country=\"XX\".".into());
            result
        };
        let Some(code) = normalize_code(value, &self.manifest.normalization) else {
            return Ok(invalid());
        };
        let country = hint.and_then(country);
        if hint.is_some() && country.is_none() {
            return Ok(invalid());
        }
        let scheme = scheme.map(str::to_ascii_lowercase);
        if scheme.as_deref().is_some_and(|s| !SCHEMES.contains(&s))
            || (scheme.as_deref() == Some("local") && country.is_none())
        {
            return Ok(invalid());
        }
        let schemes = scheme
            .as_deref()
            .map_or_else(|| vec!["iata", "icao"], |s| vec![s]);
        let mut records = Vec::new();
        for scheme in schemes {
            records.extend(self.observations(
                &format!("{scheme}\0{}\0{code}", country.as_deref().unwrap_or("")),
                evidence,
            )?);
        }
        self.forward_result(records, Kind::Airport, evidence)
    }
}

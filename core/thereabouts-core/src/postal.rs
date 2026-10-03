//! Postal codes require explicit country context and preserve leading zeroes.
use crate::{
    Error, Result,
    format::Pack,
    forward::{country, normalize_code},
    result::{Country, Kind, LookupResult, Status},
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
        let mut answer = self.forward_result(
            self.observations(&format!("{country}\0{code}"), evidence)?,
            Kind::Postal,
            evidence,
        )?;
        if answer.status == Status::Ambiguous {
            for candidate in &mut answer.candidates {
                self.postal_country(candidate, &country)?;
            }
            answer.inherit_consensus();
        } else if answer.status == Status::Matched {
            self.postal_country(&mut answer, &country)?;
        }
        Ok(answer)
    }
    fn postal_country(&self, answer: &mut LookupResult, country: &str) -> Result<()> {
        if answer.country.is_some() {
            return Ok(());
        }
        let row = self
            .metadata_index
            .countries
            .get(country)
            .and_then(|i| self.metadata.countries.get(*i))
            .ok_or_else(|| Error::Corrupt("Postal key country missing from metadata".into()))?;
        answer.country = Some(Country {
            code: country.into(),
            code3: row["alpha3"].as_str().map(str::to_owned),
            name: row["name"]
                .as_str()
                .ok_or_else(|| Error::Corrupt("Missing postal country name".into()))?
                .into(),
        });
        if let Some(evidence) = &mut answer.evidence {
            evidence.reason = Some("country_from_key".into());
        }
        Ok(())
    }
}

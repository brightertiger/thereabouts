//! Thin typed dispatch; all normalization and ranking remain in the core.
use serde::Deserialize;
use thereabouts_core::{format::Pack, result::LookupResult};

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
pub(crate) struct Query {
    pub verb: String,
    pub text: String,
    pub country: Option<String>,
    pub scheme: Option<String>,
    pub subdivision: Option<String>,
    pub series: Option<String>,
    pub prefer: Option<String>,
    pub scope: String,
    pub limit: usize,
    pub evidence: bool,
}
impl Default for Query {
    fn default() -> Self {
        Self {
            verb: String::new(),
            text: String::new(),
            country: None,
            scheme: None,
            subdivision: None,
            series: None,
            prefer: None,
            scope: "cities".into(),
            limit: 5,
            evidence: false,
        }
    }
}
impl Query {
    pub(crate) fn run(&self, pack: &Pack) -> thereabouts_core::Result<LookupResult> {
        let country = self.country.as_deref();
        match self.verb.as_str() {
            "h3" => pack.from_h3(&self.text, self.evidence),
            "postal" => pack.postal(&self.text, country, self.evidence),
            "airport" => pack.airport(&self.text, self.scheme.as_deref(), country, self.evidence),
            "locode" => pack.locode(&self.text, country, self.evidence),
            "phone" => pack.phone_in_country(&self.text, country, self.evidence),
            "ip" => pack.ip(&self.text, self.evidence),
            "plate" => pack.plate(&self.text, country, self.series.as_deref(), self.evidence),
            "geocode" => pack.geocode(
                &self.text,
                thereabouts_core::geocode::Options {
                    country,
                    subdivision: self.subdivision.as_deref(),
                    prefer: self.prefer.as_deref(),
                    scope: &self.scope,
                    limit: self.limit,
                    evidence: self.evidence,
                },
            ),
            _ => Err(thereabouts_core::Error::Input("Unknown lookup verb".into())),
        }
    }
}

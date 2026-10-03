//! Common projection and deterministic grouping of published forward associations.
use crate::{
    Error, Result,
    format::{Pack, observation::Observation, spatial::Label},
    result::{Country, Evidence, Kind, LookupResult, Match, State, Status},
};
use h3o::{LatLng, Resolution};
use std::{collections::BTreeMap, sync::Arc};
impl Pack {
    fn fallback_geography(&self, answer: &mut LookupResult, record: &Observation) {
        if answer.country.is_none()
            && let Some(code) = &record.fallback[0]
        {
            let row = self
                .metadata_index
                .countries
                .get(code)
                .and_then(|i| self.metadata.countries.get(*i));
            answer.country = Some(Country {
                code: code.clone(),
                code3: row.and_then(|r| r["alpha3"].as_str()).map(str::to_owned),
                name: row
                    .and_then(|r| r["name"].as_str())
                    .or(record.fallback[1].as_deref())
                    .unwrap_or(code)
                    .into(),
            });
        }
        if answer.state.is_none()
            && let Some(name) = &record.fallback[3]
        {
            let code = &record.fallback[2];
            let row = code
                .as_ref()
                .and_then(|c| self.metadata_index.subdivisions.get(c))
                .and_then(|i| self.metadata.subdivisions.get(*i));
            answer.state = Some(State {
                code: code.clone(),
                name: row.and_then(|r| r["name"].as_str()).unwrap_or(name).into(),
            });
        }
    }
    pub(crate) fn require_family(&self, family: &str) -> Result<()> {
        if self.manifest.family == family {
            Ok(())
        } else {
            Err(Error::Incompatible(format!("Requires a {family} pack")))
        }
    }
    pub(crate) fn forward_result(
        &self,
        records: Vec<Arc<Observation>>,
        kind: Kind,
        evidence: bool,
    ) -> Result<LookupResult> {
        let mut groups = BTreeMap::<String, LookupResult>::new();
        for record in records {
            let [country, state, city] = record.places;
            let identity = if kind == Kind::Postal && city != 0 {
                format!("{city:010}:{country:010}:{state:010}")
            } else if kind == Kind::PhonePrefix {
                format!("{country}:{state}:{city}:{:?}", record.fallback)
            } else if let Some(identity) = record.identity {
                format!("source:{identity:020}")
            } else {
                format!(
                    "{}:{}",
                    record.text.first().and_then(Option::as_deref).unwrap_or(""),
                    record.text.get(1).and_then(Option::as_deref).unwrap_or("")
                )
            };
            let mut answer = self.core.as_deref().unwrap_or(self).project(
                LookupResult::empty(Status::Matched),
                Label([country, state, city, 0, 0]),
            )?;
            self.fallback_geography(&mut answer, &record);
            answer.timezone = self.place(city, false)?.and_then(|p| p.timezone.clone());
            answer.status = Status::Matched;
            answer.kind = kind;
            answer.r#match = Some(Match::Exact);
            answer.point = record.point();
            answer.cell = answer
                .point
                .as_ref()
                .and_then(|p| LatLng::new(p.lat, p.lon).ok())
                .map(|p| p.to_cell(Resolution::Eight).to_string());
            let source = record
                .text
                .iter()
                .zip(crate::format::observation::FIELDS)
                .filter_map(|(value, name)| {
                    value
                        .as_ref()
                        .map(|v| (name.to_owned(), serde_json::Value::String(v.clone())))
                })
                .collect::<serde_json::Map<_, _>>();
            if evidence {
                answer.evidence = Some(Evidence {
                    stored_cell: None,
                    country_id: self.place(country, false)?.map(|p| p.field(0).into()),
                    state_id: self.place(state, false)?.map(|p| p.field(0).into()),
                    city_id: self.place(city, false)?.map(|p| p.field(0).into()),
                    city_method: None,
                    land_method: None,
                    reason: Some("exact_code".into()),
                    timezones: vec![],
                    source_ids: Some(serde_json::Value::Array(vec![serde_json::Value::Object(
                        source,
                    )])),
                });
            }
            if let Some(existing) = groups.get_mut(&identity) {
                if let (Some(old), Some(new)) = (&mut existing.evidence, answer.evidence)
                    && let (Some(serde_json::Value::Array(a)), Some(serde_json::Value::Array(b))) =
                        (&mut old.source_ids, new.source_ids)
                {
                    a.extend(b);
                }
            } else {
                groups.insert(identity, answer);
            }
        }
        let mut answers: Vec<_> = groups.into_values().collect();
        answers.sort_by_key(|r| {
            std::cmp::Reverse(r.city.as_ref().and_then(|c| c.population).unwrap_or(0))
        });
        if answers.len() == 1 {
            return answers
                .pop()
                .ok_or_else(|| Error::Corrupt("Lost forward result".into()));
        }
        let mut result = LookupResult::empty(if answers.is_empty() {
            Status::NotFound
        } else {
            Status::Ambiguous
        });
        result.kind = kind;
        if !answers.is_empty() {
            result.rank_basis = Some("population".into());
        }
        result.candidates = answers;
        result.inherit_consensus();
        Ok(result)
    }
}
/// Require a canonical two-letter country hint without inferring context.
pub(crate) fn country(value: &str) -> Option<String> {
    let value = value
        .trim_matches(|c: char| c.is_ascii_whitespace())
        .to_ascii_uppercase();
    (value.len() == 2 && value.bytes().all(|b| b.is_ascii_uppercase())).then_some(value)
}
/// Code normalization is explicit in the manifest and shared by lookup and export.
#[must_use]
pub fn normalize_code(value: &str, rules: &[String]) -> Option<String> {
    if value.contains('\0') {
        return None;
    }
    let mut value = value.to_owned();
    for operation in rules {
        value = match operation.as_str() {
            "strip_ascii" => value
                .trim_matches(|c: char| c.is_ascii_whitespace())
                .to_owned(),
            "upper_ascii" => value.to_ascii_uppercase(),
            "remove_ascii_spaces" => value.replace(' ', ""),
            _ => return None,
        };
    }
    (!value.is_empty()).then_some(value)
}

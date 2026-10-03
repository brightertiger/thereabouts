//! Plate inference preserves ranked evidence; one surviving country is matched.
use crate::{
    Error, Result,
    format::Pack,
    plates_index::{Hit, PlateIndex, normalize},
    result::{Country, Evidence, Kind, LookupResult, Match, State, Status},
};
use std::collections::BTreeMap;
impl Pack {
    /// Resolve a plate format and eligible registration evidence; no current vehicle location is inferred.
    pub fn plate(
        &self,
        value: &str,
        hint: Option<&str>,
        series: Option<&str>,
        evidence: bool,
    ) -> Result<LookupResult> {
        self.require_family("plates")?;
        let index = self
            .plates
            .as_ref()
            .ok_or_else(|| Error::Corrupt("Missing plate index".into()))?;
        let country = hint.and_then(crate::forward::country);
        if hint.is_some()
            && country
                .as_ref()
                .is_none_or(|c| !self.metadata_index.countries.contains_key(c))
        {
            let mut result = empty(Status::InvalidInput);
            result.hint = Some("Use plate(value, country=\"XX\") with a known ISO country.".into());
            return Ok(result);
        }
        let value = normalize(value);
        // A missing-value placeholder must not match a broad personalised-serial rule.
        if country.is_none() && value == "UNKNOWN" {
            return Ok(empty(Status::NotFound));
        }
        let valid =
            !value.is_empty() && value.chars().count() <= index.tables.policy.max_input_length;
        let matches = if valid {
            index.matches(&value, country.as_deref(), series)?
        } else {
            vec![]
        };
        if let Some(country) = country {
            return self.plate_country(
                index,
                &country,
                &matches,
                series,
                evidence,
                if valid {
                    None
                } else {
                    Some("empty_or_too_long_input")
                },
            );
        }
        let mut grouped = BTreeMap::<String, Vec<Hit>>::new();
        for hit in matches {
            grouped
                .entry(index.rule(&hit)?.country_code.clone())
                .or_default()
                .push(hit);
        }
        let mut ranked = Vec::new();
        for (country, hits) in grouped {
            let score = hits
                .iter()
                .map(|h| h.score)
                .fold(f64::NEG_INFINITY, f64::max);
            let answer = self.plate_country(
                index,
                &country,
                &hits,
                series,
                evidence,
                Some("plate_country_inferred"),
            )?;
            ranked.push((score, country, answer));
        }
        ranked.sort_by(|a, b| b.0.total_cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
        let mut result = empty(if ranked.is_empty() {
            Status::NotFound
        } else {
            Status::Ambiguous
        });
        if !ranked.is_empty() {
            result.rank_basis = Some(
                if index.tables.prior_available {
                    "plate_evidence"
                } else {
                    "plate_evidence_without_vehicle_prior"
                }
                .into(),
            );
        }
        result.candidates = ranked.into_iter().map(|(_, _, r)| r).collect();
        if result.candidates.len() == 1 {
            let mut answer = result
                .candidates
                .pop()
                .ok_or_else(|| Error::Corrupt("Missing inferred plate country".into()))?;
            answer.rank_basis = result.rank_basis;
            return Ok(answer);
        }
        result.inherit_consensus();
        Ok(result)
    }
    fn plate_country(
        &self,
        index: &PlateIndex,
        country: &str,
        hits: &[Hit],
        series: Option<&str>,
        evidence: bool,
        reason: Option<&str>,
    ) -> Result<LookupResult> {
        let row = self
            .metadata_index
            .countries
            .get(country)
            .and_then(|i| self.metadata.countries.get(*i))
            .ok_or_else(|| Error::Corrupt("Missing plate country metadata".into()))?;
        let mut answer = empty(Status::Matched);
        answer.r#match = Some(Match::Exact);
        answer.country = Some(Country {
            code: country.into(),
            code3: row["alpha3"].as_str().map(str::to_owned),
            name: row["name"]
                .as_str()
                .ok_or_else(|| Error::Corrupt("Missing country name".into()))?
                .into(),
        });
        let geography = crate::plates_geography::locate(index, country, hits, series)?;
        if reason.is_none()
            && let Some(code) = geography.state
        {
            let meta = code
                .subdivision_codes
                .iter()
                .filter_map(|c| {
                    self.metadata_index
                        .subdivisions
                        .get(c)
                        .and_then(|i| self.metadata.subdivisions.get(*i))
                })
                .collect::<Vec<_>>();
            answer.state = if meta.len() == 1 {
                meta.first().and_then(|r| {
                    r["name"].as_str().map(|name| State {
                        code: r["code"].as_str().map(str::to_owned),
                        name: name.into(),
                    })
                })
            } else {
                code.name_en
                    .as_ref()
                    .or(code.name_local.as_ref())
                    .map(|name| State {
                        code: Some(code.code.clone()),
                        name: name.clone(),
                    })
            };
        }
        if evidence {
            let mut sources = Vec::new();
            let mut ordered = hits.to_vec();
            ordered.sort_by(|a, b| {
                b.score.total_cmp(&a.score).then_with(|| {
                    index
                        .rule(a)
                        .ok()
                        .map(|r| &r.series_id)
                        .cmp(&index.rule(b).ok().map(|r| &r.series_id))
                })
            });
            for hit in ordered {
                let rule = index.rule(&hit)?;
                sources.push(source(serde_json::json!({"source":"plate_format","source_id":rule.series_id,"series_status":rule.series_status,"code":hit.code,"score":hit.score.to_string(),"match":if hit.relaxed {"separator_relaxed"} else {"exact"},"provenance":index.evidence.provenance(hit.rule)?})));
            }
            for code in geography.locations {
                let (url, license) = index.evidence.source(code)?;
                sources.push(source(serde_json::json!({"source":"plate_code","source_id":code.code,"name":code.name_en.as_ref().or(code.name_local.as_ref()),"unit_kind":code.unit_kind,"source_url":url,"license":license})));
            }
            answer.evidence = Some(Evidence {
                stored_cell: None,
                country_id: Some(format!("country:{country}")),
                state_id: None,
                city_id: None,
                city_method: None,
                land_method: None,
                reason: Some(reason.unwrap_or(geography.reason).into()),
                timezones: vec![],
                source_ids: Some(serde_json::Value::Array(sources)),
            });
        }
        Ok(answer)
    }
}
fn empty(status: Status) -> LookupResult {
    let mut result = LookupResult::empty(status);
    result.kind = Kind::Plate;
    result
}

fn source(mut value: serde_json::Value) -> serde_json::Value {
    if let Some(fields) = value.as_object_mut() {
        fields.retain(|_, v| !v.is_null());
    }
    value
}

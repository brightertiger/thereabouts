//! Canonical city-name lookup: filters precede population ranking and truncation.
use crate::{
    Error, Result,
    format::{
        Pack,
        name_search::{FUZZY_KEYS, FUZZY_ROWS, share},
        spatial::Label,
    },
    result::{Evidence, Kind, LookupResult, Match, Status},
};
use std::collections::BTreeMap;
/// City-only query options; optional full-place names are a separate future pack.
#[derive(Clone, Copy, Debug)]
pub struct Options<'a> {
    /// Optional hard ISO country filter.
    pub country: Option<&'a str>,
    /// Optional hard subdivision-code filter.
    pub subdivision: Option<&'a str>,
    /// Maximum returned candidates, from one through one hundred.
    pub limit: usize,
    /// Explicitly select the most populous candidate.
    pub prefer: Option<&'a str>,
    /// Canonical cities are currently the only supported scope.
    pub scope: &'a str,
    /// Include matched spellings and method detail.
    pub evidence: bool,
}
impl Default for Options<'_> {
    fn default() -> Self {
        Self {
            country: None,
            subdivision: None,
            limit: 5,
            prefer: None,
            scope: "cities",
            evidence: false,
        }
    }
}
impl Pack {
    /// Find towns and cities by name; never infer a street-address location.
    pub fn geocode(&self, value: &str, options: Options<'_>) -> Result<LookupResult> {
        self.require_family("core")?;
        let policy = self.manifest.name_normalization.as_ref().ok_or_else(|| {
            Error::Incompatible("Core pack lacks a city-name index; rebuild the core pack".into())
        })?;
        let country = options.country.and_then(crate::forward::country);
        if options.scope != "cities"
            || !(1..=100).contains(&options.limit)
            || options.prefer.is_some_and(|p| p != "population")
            || (options.country.is_some() && country.is_none())
            || options.subdivision.is_some_and(|s| s.trim().is_empty())
        {
            return Ok(crate::name_query::invalid(
                "Use geocode(name, country=\"XX\", subdivision=code, limit=1..100, prefer=\"population\", scope=\"cities\").",
            ));
        }
        let key = crate::name_normalization::normalize(value, policy);
        if key.is_empty() || key.chars().count() > 128 {
            return Ok(crate::name_query::invalid(
                "Use a town or city name with at most 128 normalized characters.",
            ));
        }
        let exact = self
            .names
            .iter()
            .map(|index| index.exact(&key))
            .collect::<Result<Vec<_>>>()?;
        let known = exact.iter().any(|rows| !rows.is_empty());
        if let Some(result) = crate::name_query::classify(value, known) {
            return Ok(result);
        }
        let mut filters = BTreeMap::new();
        for phase in 0_u8..3 {
            let mut grouped = BTreeMap::<u32, LookupResult>::new();
            for (ordinal, (index, exact_rows)) in self.names.iter().zip(&exact).enumerate() {
                let key_budget = share(FUZZY_KEYS, self.names.len(), ordinal);
                let row_budget = share(FUZZY_ROWS, self.names.len(), ordinal);
                let mut admitted = 0;
                let rows = match phase {
                    0 => exact_rows.clone(),
                    1 => index.prefix(&key)?,
                    _ => index.fuzzy(&key, key_budget)?,
                };
                for row in rows {
                    let ([c, s, city], alternate) = index.record(row, self.place_count)?;
                    if phase == 2 && admitted == row_budget {
                        break;
                    }
                    let allowed = if let Some(allowed) = filters.get(&(c, s)) {
                        *allowed
                    } else {
                        let allowed =
                            self.name_allowed(c, s, country.as_deref(), options.subdivision)?;
                        filters.insert((c, s), allowed);
                        allowed
                    };
                    if !allowed {
                        continue;
                    }
                    admitted += 1;
                    let mut answer = self.project(
                        LookupResult::empty(Status::Matched),
                        Label([c, s, city, 0, 0]),
                    )?;
                    let method = if phase > 0 {
                        Match::Fuzzy
                    } else if alternate {
                        Match::AlternateName
                    } else {
                        Match::Exact
                    };
                    if grouped.get(&city).is_some_and(|old| {
                        old.r#match == Some(Match::Exact) || method != Match::Exact
                    }) {
                        continue;
                    }
                    answer.kind = Kind::City;
                    answer.r#match = Some(method);
                    answer.rank_basis = Some("population".into());
                    answer.timezone = self.place(city, false)?.and_then(|p| p.timezone.clone());
                    answer.point = answer.city.as_ref().and_then(|c| c.point.clone());
                    if options.evidence {
                        answer.evidence =
                            Some(self.name_evidence(index, row, [c, s, city], phase)?);
                    }
                    grouped.insert(city, answer);
                }
            }
            if !grouped.is_empty() {
                return ranked(grouped.into_values().collect(), options);
            }
        }
        let mut result = LookupResult::empty(Status::NotFound);
        result.kind = Kind::City;
        Ok(result)
    }
    fn name_allowed(
        &self,
        country: u32,
        state: u32,
        country_filter: Option<&str>,
        subdivision: Option<&str>,
    ) -> Result<bool> {
        if let Some(filter) = country_filter
            && self
                .place(country, false)?
                .is_none_or(|p| p.field(6) != filter)
        {
            return Ok(false);
        }
        if let Some(filter) = subdivision
            && self
                .place(state, false)?
                .is_none_or(|p| !p.field(7).eq_ignore_ascii_case(filter.trim()))
        {
            return Ok(false);
        }
        Ok(true)
    }
    fn name_evidence(
        &self,
        index: &crate::format::names::Names,
        row: usize,
        places: [u32; 3],
        phase: u8,
    ) -> Result<Evidence> {
        let [country, state, city] = places;
        Ok(Evidence {
            stored_cell: None,
            country_id: self.place(country, false)?.map(|p| p.field(0).into()),
            state_id: self.place(state, false)?.map(|p| p.field(0).into()),
            city_id: self.place(city, false)?.map(|p| p.field(0).into()),
            city_method: None,
            land_method: None,
            reason: Some(
                match phase {
                    0 => "name_exact",
                    1 => "name_prefix",
                    _ => "name_trigram",
                }
                .into(),
            ),
            timezones: vec![],
            source_ids: Some(
                serde_json::json!([{"source":"city_names","source_id":index.spelling(row)?}]),
            ),
        })
    }
}
fn ranked(mut answers: Vec<LookupResult>, options: Options<'_>) -> Result<LookupResult> {
    answers.sort_by(|a, b| {
        let a = a.city.as_ref();
        let b = b.city.as_ref();
        b.and_then(|c| c.population)
            .unwrap_or(0)
            .cmp(&a.and_then(|c| c.population).unwrap_or(0))
            .then_with(|| a.map(|c| &c.id).cmp(&b.map(|c| &c.id)))
    });
    if answers.len() == 1 || options.prefer == Some("population") {
        return answers
            .into_iter()
            .next()
            .map(with_cell)
            .ok_or_else(|| Error::Corrupt("Missing name result".into()));
    }
    // A shared cell may exist even for distinct points. Stop at the first
    // disagreement; the remaining cells need computing only if returned.
    let mut common_cell = None;
    for (i, answer) in answers.iter_mut().enumerate() {
        set_cell(answer);
        if i == 0 {
            common_cell.clone_from(&answer.cell);
        } else if answer.cell != common_cell {
            common_cell = None;
            break;
        }
    }
    let mut result = LookupResult::empty(Status::Ambiguous);
    result.kind = Kind::City;
    result.rank_basis = Some("population".into());
    result.candidates = answers;
    result.inherit_consensus();
    result.cell = common_cell;
    result.candidates.truncate(options.limit);
    for answer in &mut result.candidates {
        set_cell(answer);
    }
    Ok(result)
}

fn with_cell(mut answer: LookupResult) -> LookupResult {
    set_cell(&mut answer);
    answer
}
fn set_cell(answer: &mut LookupResult) {
    if answer.cell.is_some() {
        return;
    }
    answer.cell = answer
        .point
        .as_ref()
        .and_then(|p| h3o::LatLng::new(p.lat, p.lon).ok())
        .map(|p| p.to_cell(h3o::Resolution::Eight).to_string());
}

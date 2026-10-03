//! Geographic eligibility follows declared source scope and temporal policy only.
use crate::{
    Result,
    format::plates::Code,
    plates_index::{Hit, PlateIndex},
};
pub(crate) struct Geography<'a> {
    pub(crate) state: Option<&'a Code>,
    pub(crate) locations: Vec<&'a Code>,
    pub(crate) reason: &'static str,
}
pub(crate) fn locate<'a>(
    index: &'a PlateIndex,
    country: &str,
    hits: &[Hit],
    series: Option<&str>,
) -> Result<Geography<'a>> {
    let empty = |reason| Geography {
        state: None,
        locations: vec![],
        reason,
    };
    if hits.is_empty() {
        return Ok(empty("no_matching_format"));
    }
    let policy = &index.tables.policy;
    let config = &policy.geography;
    if config.excluded_countries.iter().any(|c| c == country) {
        return Ok(empty("subdivision_series_context_required"));
    }
    if config.block_if_non_geographic_format_matches && hits.iter().any(|h| h.code.is_none()) {
        return Ok(empty("non_geographic_or_ambiguous_series"));
    }
    let mut eligible = Vec::new();
    let mut parents = Vec::new();
    for hit in hits {
        let rule = index.rule(hit)?;
        if rule.series_status == "historic"
            && config.historic_requires_explicit_series
            && series.is_none()
        {
            continue;
        }
        let code = hit.code.as_deref().unwrap_or("");
        let allowed = |row: &&Code| {
            config.allowed_scopes.contains(&row.scope)
                && (row.series_status != "unknown" || config.unknown_status_eligible)
                && row.subdivision_scope.as_ref().is_none_or(String::is_empty)
                && row.series_status == rule.series_status
                && policy.levels.contains_key(&row.unit_kind)
        };
        eligible.extend(index.known(country, code).into_iter().filter(allowed));
        if let Some(length) = config.state_prefix.get(country) {
            let prefix = index
                .code_key(code)
                .chars()
                .take(*length)
                .collect::<String>();
            parents.extend(
                index
                    .known(country, &prefix)
                    .into_iter()
                    .filter(allowed)
                    .filter(|c| {
                        policy
                            .levels
                            .get(&c.unit_kind)
                            .is_some_and(|v| v == "state")
                    }),
            );
        }
    }
    for level in ["place", "state"] {
        let mut locations = Vec::new();
        let mut seen = std::collections::BTreeSet::new();
        for code in eligible
            .iter()
            .chain(&parents)
            .filter(|c| policy.levels.get(&c.unit_kind).is_some_and(|v| v == level))
        {
            if seen.insert((
                &code.code,
                &code.name_en,
                &code.name_local,
                &code.source_url,
            )) {
                locations.push(*code);
            }
        }
        if !locations.is_empty() {
            let names = locations
                .iter()
                .map(|c| (&c.name_en, &c.name_local))
                .collect::<std::collections::BTreeSet<_>>();
            let state = if level == "state" && names.len() == 1 {
                locations.first().copied()
            } else {
                None
            };
            return Ok(Geography {
                state,
                locations,
                reason: if level == "place" {
                    "known_registration_code"
                } else {
                    "known_state_code_no_finer_verified_unit"
                },
            });
        }
    }
    Ok(empty("unknown_code_or_unverified_temporal_scope"))
}
